from collections.abc import Mapping

from app.constants.log_tags import LogTag
from app.db.repositories.notifications import notification_repository
from app.models.notification.notification_models import (
    NotificationListFilters,
    NotificationRecord,
    NotificationStatus,
)
from shared.py.wide_events import log


class MongoDBNotificationStorage:
    """Notification storage — delegates persistence to notification_repository."""

    async def save_notification(self, notification: NotificationRecord) -> None:
        """Save a notification to MongoDB."""
        await notification_repository.create(notification)

    async def get_notification(
        self, notification_id: str, user_id: str | None
    ) -> NotificationRecord | None:
        """Retrieve a notification by ID with optional user validation."""
        return await notification_repository.get_for_user(notification_id, user_id)

    async def update_notification(
        self, notification_id: str, updates: Mapping[str, object]
    ) -> None:
        """Update a notification's fields."""
        log.set_ns("notification", notification_id=notification_id)
        log.info(
            f"{LogTag.NOTIFICATION} Updating notification with updates",
            notification_id=notification_id,
            updates=updates,
        )
        await notification_repository.update_fields(notification_id, **updates)

    async def get_user_notifications(
        self,
        user_id: str,
        *,
        filters: NotificationListFilters | None = None,
    ) -> list[NotificationRecord]:
        """Get user's notifications with optional filtering."""
        return await notification_repository.list_for_user(user_id, filters=filters)

    async def get_notification_count(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
    ) -> int:
        """Get count of notifications for a user with optional status filtering."""
        return await notification_repository.count_for_user(
            user_id, status=status, channel_type=channel_type
        )

    async def mark_all_read(self, user_id: str, channel_type: str | None = None) -> int:
        """Mark every delivered notification for a user as read. Returns the count updated."""
        return await notification_repository.mark_all_read_for_user(
            user_id, channel_type=channel_type
        )
