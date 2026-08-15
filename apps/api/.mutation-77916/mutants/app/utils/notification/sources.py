from datetime import UTC, datetime

from app.models.notification.notification_models import (
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)


class AIProactiveNotificationSource:
    """Builds notifications for AI-initiated proactive actions (reminders, etc.)."""

    @staticmethod
    def create_reminder_notification(
        user_id: str,
        reminder_id: str,
        title: str,
        body: str,
        actions: list[NotificationAction],
    ) -> NotificationRequest:
        """Create notification for AI-generated reminders"""
        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_REMINDER,
            type=NotificationType.INFO,
            priority=1,
            content=NotificationContent(
                title=title,
                body=body,
                actions=actions,
            ),
            metadata={
                "reminder_id": reminder_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
