"""
User-related ARQ tasks.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_EMAIL
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.utils.notification.channel_preferences import normalize_channel_preferences
from app.utils.timezone import as_utc
from shared.py.wide_events import log


def _emails_sent_this_episode(user: UserDocument) -> int:
    """Sends in the current inactivity episode; the counter resets when the user returns."""
    last_active = as_utc(user.last_active_at)
    last_email_sent = as_utc(user.last_inactive_email_sent)

    # An email older than last_active_at belongs to a previous inactivity episode.
    if not last_email_sent or (last_active and last_email_sent < last_active):
        return 0
    # Docs written before the counter existed recorded their one send via the timestamp only.
    count: int = user.inactive_email_count or 1
    return count


def _should_send_inactive_email(user: UserDocument) -> bool:
    """Throttle policy: per inactivity episode, first email after 7 days, second 7+ days later, max 2."""
    if not normalize_channel_preferences(user.notification_channel_prefs)[CHANNEL_TYPE_EMAIL]:
        return False

    now = datetime.now(UTC)
    last_active = as_utc(user.last_active_at)
    last_email_sent = as_utc(user.last_inactive_email_sent)

    # Check if user is inactive long enough (7+ days)
    if not last_active or (now - last_active).days < 7:
        return False

    # Skip if email sent in last 7 days
    if last_email_sent and (now - last_email_sent).days < 7:
        return False

    return _emails_sent_this_episode(user) < 2


async def check_inactive_users(ctx: dict[str, Any]) -> str:  # noqa: ARG001 -- contract
    """
    Check for inactive users and send emails to those inactive for more than 7 days.
    Emails are sent only once after 7 days and once more after 14 days to avoid spam.

    Args:
        ctx: ARQ context

    Returns:
        Processing result message
    """
    # Deferred import: email delivery stack kept off worker-task module load path until the check runs
    from app.services.email import send_inactive_user_email  # noqa: PLC0415 -- deferred

    if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
        # The boundary emits one canonical event per run; the skip reason rides
        # on it instead of a standalone line.
        log.set(outcome="skipped", reason="email delivery not configured")
        return "skipped: email not configured"

    log.set(stage="checking")

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    # Convert to naive datetime for comparison with potentially naive database values
    seven_days_ago_naive = seven_days_ago.replace(tzinfo=None)

    # Find users inactive for 7+ days who haven't gotten email recently
    inactive_users = await user_repository.find_inactive_email_candidates(seven_days_ago_naive)

    log.set(inactive_users_detected=len(inactive_users))

    email_count = 0
    email_failures = 0
    for user in inactive_users:
        if not user.email or not _should_send_inactive_email(user):
            continue
        try:
            await send_inactive_user_email(user.email, user.id, user.name)
            await user_repository.record_inactive_email(
                user.id, _emails_sent_this_episode(user) + 1
            )
            email_count += 1
            log.set(sent_to_email=user.email)
        except Exception as e:
            email_failures += 1
            log.error(
                f"{LogTag.WORKER} Failed to send email",
                email=user.email,
                error=str(e),
                error_type=type(e).__name__,
            )

    log.set(
        emails_sent=email_count,
        email_failures=email_failures,
        checked_users=len(inactive_users),
        outcome="success",
    )
    return f"Processed {len(inactive_users)} inactive users, sent {email_count} emails"
