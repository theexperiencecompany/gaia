"""Nurture email engine: one declarative sequence, one send per user per run.

Driven hourly by the ARQ cron so each user is evaluated at 9am in their own
timezone. Per-user state lives on the user document under ``nurture``:
``completed_steps`` guarantees a step sends at most once ever, ``history``
enforces the frequency caps.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from app.config.settings import settings
from app.constants.email import CONTACT_EMAIL, FOUNDER_MEETING_URL, FOUNDER_SENDER
from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_EMAIL
from app.constants.nurture import (
    NURTURE_BACKFILL_GRACE_DAYS,
    NURTURE_MAX_EMAILS_PER_WEEK,
    NURTURE_MIN_DAYS_BETWEEN_EMAILS,
    NURTURE_SEND_HOUR_LOCAL,
    NURTURE_STEPS,
    NURTURE_UTM_MEDIUM,
    NURTURE_UTM_SOURCE,
    NurtureStep,
)
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.email import EmailMessage, render_email_template, send_email
from app.services.nurture.context_builders import CONTEXT_BUILDERS
from app.services.nurture.predicates import SKIP_PREDICATES
from app.utils.notification.channel_preferences import normalize_channel_preferences
from app.utils.notification.unsubscribe import build_unsubscribe_headers, build_unsubscribe_url
from app.utils.timezone import as_utc, is_within_local_daytime
from shared.py.wide_events import log


def _within_frequency_caps(history: list[dict], now: datetime) -> bool:
    sent_times = [
        sent_at
        for entry in history
        if entry.get("status") == "sent" and (sent_at := as_utc(entry.get("at")))
    ]
    if not sent_times:
        return True
    recent_week = [t for t in sent_times if now - t <= timedelta(days=7)]
    if len(recent_week) >= NURTURE_MAX_EMAILS_PER_WEEK:
        return False
    return now - max(sent_times) >= timedelta(days=NURTURE_MIN_DAYS_BETWEEN_EMAILS)


async def _record_step(user_id: str, step_key: str, now: datetime, status: str) -> None:
    await user_repository.record_nurture_step(user_id, step_key, at=now, status=status)


async def _send_step(user: UserDocument, step: NurtureStep) -> None:
    context: dict = {
        "user_name": user.name,
        "contact_email": CONTACT_EMAIL,
        "founder_meeting_url": FOUNDER_MEETING_URL,
        "unsubscribe_url": build_unsubscribe_url(user.id),
    }
    if step.cta_path:
        utm = urlencode(
            {
                "utm_source": NURTURE_UTM_SOURCE,
                "utm_medium": NURTURE_UTM_MEDIUM,
                "utm_campaign": step.key,
            }
        )
        context["cta_url"] = f"{settings.FRONTEND_URL}{step.cta_path}?{utm}"
        context["cta_label"] = step.cta_label

    # Last so a builder can override base keys (e.g. cta_label).
    if step.context_builder:
        context.update(await CONTEXT_BUILDERS[step.context_builder](user))

    await send_email(
        EmailMessage(
            sender=FOUNDER_SENDER,
            to=[user.email],
            subject=step.subject,
            html=render_email_template(step.template, **context),
            reply_to=CONTACT_EMAIL,
            headers=build_unsubscribe_headers(user.id),
        )
    )


def _step_pending(
    step: NurtureStep, days_since_signup: int, completed: set[str], onboarded: bool
) -> bool:
    """Whether a step is still eligible to send, before its skip predicate runs."""
    if not step.enabled or step.key in completed:
        return False
    in_window = (
        step.day_offset <= days_since_signup <= step.day_offset + NURTURE_BACKFILL_GRACE_DAYS
    )
    if not in_window:
        return False
    # Held, not skipped: the step stays pending and sends if onboarding
    # completes while its window is still open.
    return not (step.requires_onboarding and not onboarded)


async def _select_step(
    user: UserDocument, days_since_signup: int, completed: set[str], now: datetime
) -> NurtureStep | None:
    """First pending step whose skip predicate doesn't fire; predicate hits are recorded as skipped."""
    onboarded = bool((user.onboarding or {}).get("completed"))
    for step in NURTURE_STEPS:
        if not _step_pending(step, days_since_signup, completed, onboarded):
            continue
        if step.skip_predicate and await SKIP_PREDICATES[step.skip_predicate](user):
            await _record_step(user.id, step.key, now, status="skipped")
            continue
        return step
    return None


async def _process_user(user: UserDocument, now: datetime) -> bool:
    """Evaluate one user against the sequence; sends at most one email. Returns True on send."""
    # Send only during the user's local NURTURE_SEND_HOUR_LOCAL hour.
    if not is_within_local_daytime(
        now, user.timezone, NURTURE_SEND_HOUR_LOCAL, NURTURE_SEND_HOUR_LOCAL + 1
    ):
        return False
    if not user.email:
        return False
    if not normalize_channel_preferences(user.notification_channel_prefs)[CHANNEL_TYPE_EMAIL]:
        return False

    created_at = as_utc(user.created_at)
    if not created_at:
        return False

    state = user.nurture or {}
    if not _within_frequency_caps(state.get("history") or [], now):
        return False

    completed = set(state.get("completed_steps") or [])
    step = await _select_step(user, (now - created_at).days, completed, now)
    if step is None:
        return False

    await _send_step(user, step)
    await _record_step(user.id, step.key, now, status="sent")
    capture_event(
        user.id,
        AnalyticsEvents.NURTURE_EMAIL_SENT,
        {"step": step.key, "day_offset": step.day_offset},
    )
    log.set(user={"id": user.id}, nurture={"step": step.key})
    log.info(f"{LogTag.MAIL} Nurture email sent", step_key=step.key)
    return True


async def run_nurture_sequence() -> str:
    """Send due nurture emails to users whose local time is the send hour."""
    if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
        log.info(f"{LogTag.MAIL} Nurture run skipped: email delivery not configured")
        return "skipped: email not configured"

    now = datetime.now(UTC)
    max_window_days = (
        max(step.day_offset for step in NURTURE_STEPS if step.enabled) + NURTURE_BACKFILL_GRACE_DAYS
    )
    # Naive cutoff: created_at is stored naive-UTC by signup (see check_inactive_users).
    cutoff = (now - timedelta(days=max_window_days + 1)).replace(tzinfo=None)

    sent = 0
    checked = 0
    for user in await user_repository.find_nurture_candidates(cutoff):
        checked += 1
        try:
            if await _process_user(user, now):
                sent += 1
        except Exception as e:
            # One user's failure must not starve the rest of the cohort.
            log.error(
                f"{LogTag.MAIL} Nurture failed for user",
                user_id=user.id,
                error=str(e),
                error_type=type(e).__name__,
            )

    log.set(nurture={"checked": checked, "sent": sent})
    return f"nurture: sent {sent} of {checked} candidates"
