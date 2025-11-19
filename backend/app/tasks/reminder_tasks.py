"""
Reminder task handlers for static reminders only.
"""

from app.config.loggers import general_logger as logger
from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.services.notification_service import notification_service
from app.utils.notification.sources import AIProactiveNotificationSource


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

    logger.info(
        f"Static reminder {reminder.id} sent notification to user {reminder.user_id}"
    )


async def execute_reminder_by_agent(
    reminder: ReminderModel,
):
    """
    Execute a static reminder task.

    This is the main entry point for reminder execution. Only handles
    STATIC reminders that send simple notifications.

    Args:
        reminder: The reminder to execute
    """
    logger.info(f"Executing reminder: {reminder.id} for agent: {reminder.agent}")

    if not reminder.id:
        logger.error(f"Reminder {reminder.id} has no ID, skipping execution.")
        raise ValueError(f"Reminder {reminder.id} has no ID, skipping execution.")

    try:
        if reminder.agent == AgentType.STATIC:
            await _execute_static_reminder(reminder)
        else:
            raise ValueError(f"Unknown agent type: {reminder.agent}")

        logger.info(
            f"Reminder {reminder.id} executed successfully for agent: {reminder.agent}"
        )
    except Exception as e:
        logger.error(f"Failed to execute reminder {reminder.id}: {str(e)}")
        raise
