"""Badge checks — rare, real-event-only, run once a day inside the briefing.

Each badge is earnable once (``awards`` unique index). Newly earned badges are
delivered as a notification and returned so the current briefing can mention
them. No points, no effort rewards, no badge-cabinet page.
"""

from app.constants.briefing import (
    BADGE_FIRST_APPROVE,
    BADGE_FIRST_OVERNIGHT_SHIPMENT,
    BADGE_GAIA_100_TODOS,
    BADGE_STREAK_7,
    BADGE_STREAK_30,
    GAIA_TODOS_CENTURY,
    OVERNIGHT_END_HOUR,
    OVERNIGHT_START_HOUR,
    STREAK_7_DAYS,
    STREAK_30_DAYS,
)
from app.db.repositories.awards import award_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.briefing.context import UserClock
from app.services.notification_service import notification_service
from shared.py.wide_events import log

# key -> (title, one-line body) for the earned-badge notification + brief mention.
BADGE_META: dict[str, tuple[str, str]] = {
    BADGE_FIRST_APPROVE: ("First approval", "You approved your first GAIA todo. The loop is live."),
    BADGE_FIRST_OVERNIGHT_SHIPMENT: (
        "Overnight shipment",
        "GAIA shipped work for you while you slept.",
    ),
    BADGE_GAIA_100_TODOS: ("100 done by GAIA", "GAIA has completed 100 todos for you."),
    BADGE_STREAK_7: ("7-day streak", "A full week of getting things done."),
    BADGE_STREAK_30: ("30-day streak", "Thirty days straight. Rare air."),
}


async def _has_overnight_shipment(user_id: str, clock: UserClock) -> bool:
    for doc in await todo_repository.list_gaia_completed(user_id):
        if doc.completed_at is None:
            continue
        hour = doc.completed_at.astimezone(clock.tz).hour
        if hour >= OVERNIGHT_START_HOUR or hour < OVERNIGHT_END_HOUR:
            return True
    return False


async def check_and_award_badges(user_id: str, clock: UserClock, streak: int) -> list[str]:
    """Award any newly earned badges; return human labels for the brief to mention."""
    already = await award_repository.get_awarded_keys(user_id)
    earned: dict[str, bool] = {}

    if BADGE_FIRST_APPROVE not in already:
        earned[BADGE_FIRST_APPROVE] = await user_repository.has_first_approve(user_id)
    if BADGE_GAIA_100_TODOS not in already:
        earned[BADGE_GAIA_100_TODOS] = (
            await todo_repository.count_gaia_completed(user_id) >= GAIA_TODOS_CENTURY
        )
    if BADGE_FIRST_OVERNIGHT_SHIPMENT not in already:
        earned[BADGE_FIRST_OVERNIGHT_SHIPMENT] = await _has_overnight_shipment(user_id, clock)
    if BADGE_STREAK_7 not in already:
        earned[BADGE_STREAK_7] = streak >= STREAK_7_DAYS
    if BADGE_STREAK_30 not in already:
        earned[BADGE_STREAK_30] = streak >= STREAK_30_DAYS

    labels: list[str] = []
    for key, qualifies in earned.items():
        if not qualifies:
            continue
        if not await award_repository.award_badge(user_id, key):
            continue  # lost a race — already held
        title, body = BADGE_META[key]
        labels.append(title)
        await _notify_badge(user_id, title, body)
        log.info("briefing.badge_awarded", user_id=user_id, badge=key)

    return labels


async def _notify_badge(user_id: str, title: str, body: str) -> None:
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.SUCCESS,
                priority=2,
                content=NotificationContent(title=f"Badge earned: {title}", body=body),
                metadata={"badge": True},
            )
        )
    except Exception as e:
        log.warning("briefing.badge_notify_failed", user_id=user_id, error=str(e))
