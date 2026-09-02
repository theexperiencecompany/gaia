from datetime import UTC, datetime

from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.notification.notification_models import (
    ChannelConfig,
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
        """Create notification for AI-generated reminders.

        Pinned to the in-app channel only: the bot-platform delivery (Telegram,
        WhatsApp, …) is handled by ``deliver_result_to_platforms``, which — unlike
        the notification system's lean external adapters — also records the
        delivery into the conversation's langgraph thread so a later turn can
        backtrack to the reminder. Auto-injecting the external channels here would
        double-send and leave the platform copy unrecorded.
        """
        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_REMINDER,
            type=NotificationType.INFO,
            priority=1,
            channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
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
