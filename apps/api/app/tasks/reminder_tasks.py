"""
Reminder task handlers for static reminders only.
"""

from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.notification_service import notification_service
from app.utils.notification.sources import AIProactiveNotificationSource
from shared.py.wide_events import log


async def _execute_static_reminder(reminder: ReminderModel) -> None:
    """
    Execute a static reminder by sending a simple notification.

    Args:
        reminder: The static reminder to execute
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

    log.info("Static reminder sent notification", reminder_id=reminder.id, user_id=reminder.user_id)


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
