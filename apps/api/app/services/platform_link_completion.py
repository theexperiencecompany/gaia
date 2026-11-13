"""The shared tail of every successful platform link.

Two routes create a link and each owes the same follow-through — the "you're
connected" greeting, the account-FS sync, the analytics event, the audit trail
on a rejected attempt:

- POST /platform-links/{platform} — the bot mints a token, the web redeems it.
- POST /bot/redeem-link-code — the web mints a code, the bot redeems it.

They live in different routers, so without one implementation they drift. It
lives here rather than in platform_link_service because
bot_queue already imports that module.
"""

from collections.abc import Mapping

from app.constants.outbound import OUTBOUND_QUEUES
from app.models.chat_models import ConversationSource
from app.models.ownership_models import DeliveryPolicy
from app.models.platform_models import PlatformLinkCompletion
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import capture
from app.services.onboarding.onboarding_service import complete_onboarding_on_platform_link
from app.services.outbox.intake import submit
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.services.outbox.prerendered import PrerenderedKind, PrerenderedMessage
from app.services.platform_link_service import (
    AccountHasDifferentPlatformError,
    PlatformAccountTakenError,
    PlatformLinkService,
    link_conflict_error,
)
from app.utils import clock
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnected
from shared.py.wide_events import log


class PostLinkSideEffectError(Exception):
    """Raised when the follow-through failed but the account link is written.

    The distinction is what a caller holding a single-use credential (a one-tap
    link code, a link token) acts on: a refusal leaves the credential good for
    the retry it asks for, while this one must spend it. Redeemed a second time
    it would find the link already there and publish the first contact again.
    """


def _greeting(
    source: ConversationSource, first_contact: list[str] | None, is_new_link: bool
) -> PrerenderedMessage | None:
    """Return what GAIA says on a freshly linked chat app: the first contact when given, else a confirmation of a new link."""
    if first_contact:
        return PrerenderedMessage(kind=PrerenderedKind.FIRST_CONTACT, bubbles=first_contact)
    if is_new_link:
        return PrerenderedMessage(kind=PrerenderedKind.ACCOUNT_LINKED, platform=source.display_name)
    return None


def _platform_notice(
    user_id: str, source: ConversationSource, connected_at: str, message: PrerenderedMessage
) -> NoticeReport:
    """Build the notice that says message on source, the chat app just linked, whatever the user is doing."""
    occurrence = f"{message.kind.value}:{source.value}:{connected_at}"
    return NoticeReport(
        report_id=occurrence,
        recipient=user_id,
        producer=ProducerKind.ACCOUNT,
        subject=Subject(kind=SubjectKind.ACCOUNT, id=occurrence, label=source.display_name),
        occurred_at=clock.now(),
        initiative=Initiative.ASKED,
        delivery_policy=DeliveryPolicy(channel=source),
        outcome=NoticeOutcome.INFO,
        prerendered=message,
    )


async def complete_platform_link(
    user_id: str,
    platform: str,
    platform_user_id: str,
    profile: Mapping[str, str | None] | None = None,
    *,
    first_contact: list[str] | None = None,
) -> PlatformLinkCompletion:
    """Link the account and run every side effect a successful link owes.

    first_contact, when given, is submitted to the outbox as-is; the result reports
    whether the platform has a queue to carry it, since otherwise nothing sends it.
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
        # A bare ValueError (empty platform_user_id, a missing user) is deliberately
        # NOT caught here: it's an internal fault, not a 409.
        raise link_conflict_error(e) from e

    # Everything below runs against a link that is already written: a failure is
    # re-raised, nothing swallowed, but named so a caller holding a single-use
    # credential spends it instead of handing it back for a duplicate retry.
    try:
        source = ConversationSource.coerce(platform)
        carrier = source if source in OUTBOUND_QUEUES else None
        delivered = carrier is not None or not first_contact
        if carrier is not None:
            greeting = _greeting(carrier, first_contact, result.is_new_link)
            if greeting is not None:
                await submit(_platform_notice(user_id, carrier, result.connected_at, greeting))
        elif first_contact:
            # The link itself held; the one message a new user is guaranteed
            # to read has no queue to travel. Loud, because nothing else will retry it —
            # and reported back so the caller can have the bot send it instead.
            log.warning(
                "first contact has no outbound queue after a one-tap link",
                platform=platform,
                user_id=user_id,
            )
        schedule_account_sync(user_id)
        if result.is_new_link:
            await complete_onboarding_on_platform_link(user_id)
            # Only a link that did not exist a moment ago is a connection, so an
            # idempotent re-link never captures.
            capture(
                UserId(user_id),
                IntegrationConnected(integration_id=platform, is_new_link=result.is_new_link),
            )
    except Exception as e:
        raise PostLinkSideEffectError(
            f"the {platform} link was written but its follow-through failed: {e}"
        ) from e
    return PlatformLinkCompletion(link=result, first_contact_delivered=delivered)
