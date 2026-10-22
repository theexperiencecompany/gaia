"""User-related ARQ tasks."""

from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_EMAIL
from app.constants.user_activity import REACTIVATE_USER_RETRY_DELAY, ActivityStatus
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.services.user_activity.reactivation import reactivate_user
from app.utils.notification.channel_preferences import normalize_channel_preferences
from app.utils.timezone import as_utc
from app.workers.task_envelope import RETRY_BACKOFF_BASE, ArqJobContext
from shared.py.wide_events import UserContext, log

# Days between the (at most two) nudges an idle user gets per idle episode.
INACTIVE_EMAIL_SPACING = timedelta(days=7)
MAX_INACTIVE_EMAILS_PER_EPISODE = 2


def _emails_sent_this_episode(user: UserDocument) -> int:
    """Count sends in the current inactivity episode; the counter resets when the user returns."""
    last_active = as_utc(user.last_active_at)
    last_email_sent = as_utc(user.last_inactive_email_sent)

    # An email older than last_active_at belongs to a previous inactivity episode.
    if not last_email_sent or (last_active and last_email_sent < last_active):
        return 0
    # Docs written before the counter existed recorded their one send via the timestamp only.
    count: int = user.inactive_email_count or 1
    return count


def _should_send_inactive_email(user: UserDocument, now: datetime) -> bool:
    """Throttle an idle user's nudges: email on, one per spacing window, at most two per episode."""
    if not normalize_channel_preferences(user.notification_channel_prefs)[CHANNEL_TYPE_EMAIL]:
        return False
    last_email_sent = as_utc(user.last_inactive_email_sent)
    if last_email_sent and now - last_email_sent < INACTIVE_EMAIL_SPACING:
        return False
    return _emails_sent_this_episode(user) < MAX_INACTIVE_EMAILS_PER_EPISODE


async def check_inactive_users(ctx: dict[str, Any]) -> str:  # noqa: ARG001 -- contract
    """Nudge idle users back by email; a dormant user is past nudging and gets none."""
    # Deferred import: email delivery stack kept off worker-task module load path until the check runs
    from app.services.email import send_inactive_user_email  # noqa: PLC0415 -- deferred

    if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
        # The boundary emits one canonical event per run; the skip reason rides
        # on it instead of a standalone line.
        log.set(outcome="skipped", reason="email delivery not configured")
        return "skipped: email not configured"

    log.set(stage="checking")

    now = datetime.now(UTC)
    idle_users = await user_repository.find_by_activity_status(ActivityStatus.IDLE)

    log.set(inactive_users_detected=len(idle_users))

    email_count = 0
    email_failures = 0
    for user in idle_users:
        if not user.email or not _should_send_inactive_email(user, now):
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
        checked_users=len(idle_users),
        outcome="success",
    )
    return f"Processed {len(idle_users)} inactive users, sent {email_count} emails"


async def reactivate_user_task(ctx: ArqJobContext, user_id: str) -> str:
    """Resume what was paused while user_id was dormant, retrying until it all resumes.

    Queued by record_activity on a dormant user's first activity, which has
    already marked them active, so this task is the only thing coming back for
    the paused work.
    """
    job_try = ctx.get("job_try", 1)
    log.set(user=UserContext(id=user_id))
    try:
        resumed = await reactivate_user(user_id)
    except Exception as e:
        # Broad on purpose: whatever stopped the resume, Retry re-raises it and
        # max_tries bounds the chain.
        defer = REACTIVATE_USER_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            "user.reactivation_incomplete",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e
    return f"reactivated {user_id}: resumed {resumed}"
