"""The shared tail of every successful platform link.

Two routes create a link and each owes the same follow-through — the "you're
connected" greeting, the account-FS sync, the analytics event, the audit trail
on a rejected attempt:

- ``POST /platform-links/{platform}`` — the bot mints a token, the web redeems it.
- ``POST /bot/redeem-link-code`` — the web mints a code, the bot redeems it.

They live in different routers, so without one implementation they drift. It
lives here rather than in ``platform_link_service`` because
``outbound_delivery`` already imports that module.
"""

from collections.abc import Mapping

from app.constants.outbound import OUTBOUND_TTL_SECONDS_GREETING
from app.constants.platform_links import (
    LINK_CONFLICT_ACCOUNT_HAS_OTHER,
    LINK_CONFLICT_PLATFORM_TAKEN,
)
from app.models.chat_models import ConversationSource
from app.models.platform_models import PlatformLinkCompletion
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.outbound_delivery import (
    OutboundResult,
    notify_account_linked,
    publish_outbound_message,
)
from app.services.platform_link_service import (
    AccountHasDifferentPlatformError,
    PlatformAccountTakenError,
    PlatformLinkService,
)
from app.utils.errors import create_error
from shared.py.wide_events import log


class PostLinkSideEffectError(Exception):
    """Raised when the follow-through failed but the account link is written.

    The distinction is what a caller holding a single-use credential (a one-tap
    link code, a link token) acts on: a refusal leaves the credential good for
    the retry it asks for, while this one must spend it. Redeemed a second time
    it would find the link already there and publish the first contact again.
    """


async def complete_platform_link(
    user_id: str,
    platform: str,
    platform_user_id: str,
    profile: Mapping[str, str | None] | None = None,
    *,
    first_contact: list[str] | None = None,
) -> PlatformLinkCompletion:
    """Link the account and run every side effect a successful link owes.

    first_contact, when given, is delivered as-is on the outbound queue; the
    result reports whether it went out, since nothing retries the publish.
    Raises AppError(409) when the platform account belongs to another user, and
    PostLinkSideEffectError for any failure after the link is already written.
    """
    try:
        result = await PlatformLinkService.link_account(
            user_id, platform, platform_user_id, profile=profile
        )
    except (PlatformAccountTakenError, AccountHasDifferentPlatformError) as e:
        # No raw identifiers beyond the resource being linked: the actor,
        # provider and reason are what make a rejected attempt findable.
        log.audit(
            "platform account link rejected",
            actor=user_id,
            resource=platform_user_id,
            provider=platform,
            error_type=type(e).__name__,
            error=str(e),
        )
        # Two different conflicts wearing one 409 sent people to fix the wrong
        # account: told "disconnect it from the other GAIA account", a user whose
        # own account merely holds a different handle goes looking for an account
        # that does not exist. The code travels with the response so the bots can
        # stop inferring the reason from the status alone.
        #
        # An empty platform_user_id or a missing user still raises the plain
        # ValueError that ``link_account`` documents, and is deliberately NOT
        # caught here: neither is something the person linking can act on, and
        # dressing an internal fault as a 409 is how "User not found" came to be
        # reported to users as an ownership conflict.
        if isinstance(e, PlatformAccountTakenError):
            raise create_error(
                message=str(e),
                why="the platform account is already linked to a different GAIA account",
                fix="disconnect it from the other account, or link a different one",
                status_code=409,
                code=LINK_CONFLICT_PLATFORM_TAKEN,
            ) from e
        raise create_error(
            message=str(e),
            why="this GAIA account already has a different account on this platform",
            fix="disconnect the one you already have in settings, then link this one",
            status_code=409,
            code=LINK_CONFLICT_ACCOUNT_HAS_OTHER,
        ) from e

    # Everything below runs against a link that is already written: a failure is
    # re-raised, nothing swallowed, but named so a caller holding a single-use
    # credential spends it instead of handing it back for a duplicate retry.
    try:
        delivered = True
        if first_contact:
            delivery = await publish_outbound_message(
                ConversationSource.coerce(platform) or ConversationSource.WEB,
                user_id,
                first_contact,
                ttl_seconds=OUTBOUND_TTL_SECONDS_GREETING,
            )
            delivered = delivery is OutboundResult.PUBLISHED
            if not delivered:
                # The link itself held; the one message a new user is guaranteed
                # to read did not. Loud, because nothing else will retry it — and
                # reported back so the caller can have the bot send it instead.
                log.warning(
                    "first contact was not delivered after a one-tap link",
                    platform=platform,
                    user_id=user_id,
                    outcome=delivery.value,
                )
        elif result.is_new_link:
            await notify_account_linked(platform, user_id)
        schedule_account_sync(user_id)
        if result.is_new_link:
            # Only a link that did not exist a moment ago is a connection, so an
            # idempotent re-link never captures. capture_event, not the context one:
            # the bot route has no session identity to inherit.
            capture_event(
                user_id,
                AnalyticsEvents.INTEGRATION_CONNECTED,
                {"integration_id": platform, "is_new_link": result.is_new_link},
            )
    except Exception as e:
        raise PostLinkSideEffectError(
            f"the {platform} link was written but its follow-through failed: {e}"
        ) from e
    return PlatformLinkCompletion(link=result, first_contact_delivered=delivered)
