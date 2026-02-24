from datetime import datetime, timezone
from typing import List

from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)


class AIProactiveNotificationSource:
    """
    Notification source for AI-initiated proactive actions.

    This class contains static methods to create notifications for various
    AI-driven proactive actions like email composition, calendar events,
    and task creation that are initiated by backend workers.
    """

    @staticmethod
    def create_reminder_notification(
        user_id: str,
        reminder_id: str,
        title: str,
        body: str,
        actions: List[NotificationAction],
    ) -> NotificationRequest:
        """Create notification for AI-generated reminders"""
        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_REMINDER,
            type=NotificationType.INFO,
            priority=1,
            channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
            content=NotificationContent(
                title=title,
                body=body,
                actions=actions,
            ),
            metadata={
                "reminder_id": reminder_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
