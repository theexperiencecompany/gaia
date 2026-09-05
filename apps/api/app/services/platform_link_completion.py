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

from app.models.platform_models import PlatformLinkResult
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.outbound_delivery import notify_account_linked
from app.services.platform_link_service import PlatformLinkService
from app.utils.errors import create_error
from shared.py.wide_events import log


async def complete_platform_link(
    user_id: str,
    platform: str,
    platform_user_id: str,
    profile: Mapping[str, str | None] | None = None,
) -> PlatformLinkResult:
    """Link the account and run every side effect a successful link owes.

    Raises AppError(409) when the platform account belongs to another GAIA user
    (or the user already has a different account on this platform) — the one
    failure a caller is expected to report back to the person linking.
    """
    try:
        result = await PlatformLinkService.link_account(
            user_id, platform, platform_user_id, profile=profile
        )
    except ValueError as e:
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
        raise create_error(
            message=str(e),
            why="the platform account is already linked to a different GAIA account",
            fix="disconnect it from the other account, or link a different one",
            status_code=409,
        ) from e

    if result.is_new_link:
        await notify_account_linked(platform, user_id)
    schedule_account_sync(user_id)
    # capture_event, not capture_context_event: the bot route resolves its user
    # from the link code, not a session, so there is no request identity to
    # inherit and the event would land on an anonymous profile.
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_CONNECTED,
        {"integration_id": platform, "is_new_link": result.is_new_link},
    )
    return result
