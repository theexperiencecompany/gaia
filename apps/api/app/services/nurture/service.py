"""Nurture email engine: one declarative sequence, one send per user per run.

Driven hourly by the ARQ cron so each user is evaluated at 9am in their own
timezone. Per-user state lives on the user document under ``nurture``:
``completed_steps`` guarantees a step sends at most once ever, ``history``
enforces the frequency caps.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId

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
from app.db.mongodb.collections import users_collection
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.email import EmailMessage, render_email_template, send_email
from app.services.nurture.predicates import SKIP_PREDICATES
from app.utils.notification.channel_preferences import normalize_channel_preferences
from app.utils.notification.unsubscribe import build_unsubscribe_headers, build_unsubscribe_url
from shared.py.wide_events import log

_USER_PROJECTION = {
    "name": 1,
    "email": 1,
    "created_at": 1,
    "timezone": 1,
    "onboarding.completed": 1,
    "platform_links": 1,
    "notification_channel_prefs": 1,
    "nurture": 1,
}


def _as_utc(dt: datetime | None) -> datetime | None:
    # MongoDB may return naive datetimes
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def _local_hour(tz_name: str | None, now: datetime) -> int:
    # Missing or invalid timezone falls back to UTC by design (plan: GAIA-523).
    try:
        tz = ZoneInfo(tz_name) if tz_name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    return now.astimezone(tz).hour


def _within_frequency_caps(history: list[dict], now: datetime) -> bool:
    sent_times = [
        sent_at
        for entry in history
        if entry.get("status") == "sent" and (sent_at := _as_utc(entry.get("at")))
    ]
    if not sent_times:
        return True
    recent_week = [t for t in sent_times if now - t <= timedelta(days=7)]
    if len(recent_week) >= NURTURE_MAX_EMAILS_PER_WEEK:
        return False
    return now - max(sent_times) >= timedelta(days=NURTURE_MIN_DAYS_BETWEEN_EMAILS)


async def _record_step(user_id: ObjectId, step_key: str, now: datetime, status: str) -> None:
    await users_collection.update_one(
        {"_id": user_id},
        {
            "$addToSet": {"nurture.completed_steps": step_key},
            "$push": {"nurture.history": {"step": step_key, "at": now, "status": status}},
        },
    )


async def _send_step(user: dict, step: NurtureStep) -> None:
    user_id = str(user["_id"])
    context: dict = {
        "user_name": user.get("name"),
        "contact_email": CONTACT_EMAIL,
        "founder_meeting_url": FOUNDER_MEETING_URL,
        "unsubscribe_url": build_unsubscribe_url(user_id),
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

    await send_email(
        EmailMessage(
            sender=FOUNDER_SENDER,
            to=[user["email"]],
            subject=step.subject,
            html=render_email_template(step.template, **context),
            reply_to=CONTACT_EMAIL,
            headers=build_unsubscribe_headers(user_id),
        )
    )


async def _process_user(user: dict, now: datetime) -> bool:
    """Evaluate one user against the sequence; sends at most one email. Returns True on send."""
    if _local_hour(user.get("timezone"), now) != NURTURE_SEND_HOUR_LOCAL:
        return False
    if not user.get("email"):
        return False
    if not normalize_channel_preferences(user.get("notification_channel_prefs"))[
        CHANNEL_TYPE_EMAIL
    ]:
        return False

    created_at = _as_utc(user.get("created_at"))
    if not created_at:
        return False
    days_since_signup = (now - created_at).days

    state = user.get("nurture") or {}
    completed = set(state.get("completed_steps") or [])
    if not _within_frequency_caps(state.get("history") or [], now):
        return False

    onboarded = bool(user.get("onboarding", {}).get("completed"))

    for step in NURTURE_STEPS:
        if not step.enabled or step.key in completed:
            continue
        in_window = (
            step.day_offset <= days_since_signup <= step.day_offset + NURTURE_BACKFILL_GRACE_DAYS
        )
        if not in_window:
            continue
        # Held, not skipped: the step stays pending and sends if onboarding
        # completes while its window is still open.
        if step.requires_onboarding and not onboarded:
            continue
        if step.skip_predicate and await SKIP_PREDICATES[step.skip_predicate](user):
            await _record_step(user["_id"], step.key, now, status="skipped")
            continue

        await _send_step(user, step)
        await _record_step(user["_id"], step.key, now, status="sent")
        capture_event(
            user["email"],
            AnalyticsEvents.NURTURE_EMAIL_SENT,
            {"step": step.key, "day_offset": step.day_offset},
        )
        log.info(f"{LogTag.MAIL} Nurture email '{step.key}' sent to {user['email']}")
        return True
    return False


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
    cursor = users_collection.find(
        {"created_at": {"$gte": cutoff}, "is_active": {"$ne": False}},
        _USER_PROJECTION,
    )
    async for user in cursor:
        checked += 1
        try:
            if await _process_user(user, now):
                sent += 1
        except Exception as e:
            # One user's failure must not starve the rest of the cohort.
            log.error(f"{LogTag.MAIL} Nurture failed for user {user.get('_id')}: {e!s}")

    log.set(nurture={"checked": checked, "sent": sent})
    return f"nurture: sent {sent} of {checked} candidates"
