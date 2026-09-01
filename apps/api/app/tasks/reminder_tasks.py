"""
Reminder task handlers for static reminders only.
"""

from typing import cast

from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.notification_service import notification_service
from app.services.user_service import get_user_by_id
from app.utils.notification.sources import AIProactiveNotificationSource
from shared.py.wide_events import log


def _reminder_result_text(payload: StaticReminderPayload) -> str:
    """The reminder body as GAIA would voice it into a chat: bold title, then body."""
    segments = [
        seg for seg in (f"**{payload.title}**" if payload.title else "", payload.body) if seg
    ]
    return "\n".join(segments)


async def _execute_static_reminder(reminder: ReminderModel) -> None:
    """Fire a static reminder: raise the in-app badge and deliver it into the
    user's linked chat platforms, recorded into the conversation's langgraph thread.
    """
    if not isinstance(reminder.payload, StaticReminderPayload):
        raise ValueError("Invalid payload type for static reminder")

    if not reminder.id:
        raise ValueError("Reminder must have an ID")

    notification = AIProactiveNotificationSource.create_reminder_notification(
        title=reminder.payload.title,
        body=reminder.payload.body,
        reminder_id=reminder.id,
        user_id=reminder.user_id,
        actions=[],
    )

    await notification_service.create_notification(notification)

    # Deliver into the user's real chat platforms via the same path a finished
    # workflow uses — so the reminder lands as a GAIA message AND is recorded into
    # the platform conversation's langgraph thread, framed with the reminder id so
    # a later turn can backtrack to it. Best-effort; the in-app badge above is the
    # primary delivery. The notification itself is pinned to in-app, so this is the
    # only platform send (no double delivery).
    await _deliver_reminder_to_platforms(reminder)

    log.info("Static reminder sent notification", reminder_id=reminder.id, user_id=reminder.user_id)


async def _deliver_reminder_to_platforms(reminder: ReminderModel) -> None:
    """Push a fired reminder into the user's linked chat platforms and record it
    into the conversation thread. Best-effort — never fails the reminder.

    This is a supplementary side channel; the in-app badge is the primary
    delivery and has already succeeded by the time we get here. So every failure
    is swallowed and logged, never propagated — in particular get_user_by_id
    raises HTTPException on a transient user-repo error, which must not mark the
    reminder failed (and skip the recurring re-arm) over a side channel.
    """
    if not isinstance(reminder.payload, StaticReminderPayload) or not reminder.id:
        return
    try:
        user_data = await get_user_by_id(reminder.user_id)
        if not user_data:
            log.warning(
                "Reminder platform delivery skipped: user not found",
                reminder_id=reminder.id,
                user_id=reminder.user_id,
            )
            return
        # get_user_by_id returns the raw Mongo doc keyed by _id; downstream
        # delivery (update_messages ownership, session keying) reads user_id, so
        # stamp it — the same normalization the tracked-todo worker does.
        user_data["user_id"] = reminder.user_id
        user = cast(AuthenticatedUser, user_data)
        title = reminder.payload.title
        origin = (
            f'reminder "{title}" (id {reminder.id})' if title else f"reminder (id {reminder.id})"
        )
        await deliver_result_to_platforms(
            user=user,
            user_id=reminder.user_id,
            notification_text=_reminder_result_text(reminder.payload),
            origin=origin,
        )
    except Exception as e:  # side channel; the in-app badge already delivered
        log.error(
            "Reminder platform delivery failed",
            reminder_id=reminder.id,
            user_id=reminder.user_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def execute_reminder_by_agent(
    reminder: ReminderModel,
) -> None:
    """
    Execute a static reminder task.

    This is the main entry point for reminder execution. Only handles
    STATIC reminders that send simple notifications.

    Args:
        reminder: The reminder to execute
    """
    log.info("Executing reminder", reminder_id=reminder.id, agent=reminder.agent)

    if not reminder.id:
        log.error("Reminder has no ID, skipping execution", agent=reminder.agent)
        raise ValueError(f"Reminder {reminder.id} has no ID, skipping execution.")

    try:
        if reminder.agent == AgentType.STATIC:
            await _execute_static_reminder(reminder)
        else:
            raise ValueError(f"Unknown agent type: {reminder.agent}")

        log.info("Reminder executed successfully", reminder_id=reminder.id, agent=reminder.agent)
        capture_event(
            reminder.user_id,
            AnalyticsEvents.REMINDER_COMPLETED,
            {"reminder_id": reminder.id, "agent": reminder.agent.value},
        )
    except Exception as e:
        log.error(
            "Failed to execute reminder",
            reminder_id=reminder.id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise
