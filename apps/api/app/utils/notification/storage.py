from typing import Any

from app.constants.log_tags import LogTag
from app.db.repositories.notifications import notification_repository
from app.models.notification.notification_models import (
    NotificationRecord,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from shared.py.wide_events import log

# class NotificationStorage(ABC):
#     """Abstract storage interface"""

#     @abstractmethod
#     async def save_notification(self, notification: NotificationRecord) -> None:
#         pass

#     @abstractmethod
#     async def get_notification(
#         self, notification_id: str, user_id: str | None
#     ) -> Optional[NotificationRecord]:
#         pass

#     @abstractmethod
#     async def update_notification(
#         self, notification_id: str, updates: Dict[str, Any]
#     ) -> None:
#         pass

#     @abstractmethod
#     async def get_user_notifications(
#         self,
#         user_id: str,
#         status: Optional[NotificationStatus] = None,
#         limit: int = 50,
#         offset: int = 0,
#         channel_type: Optional[str] = None,
#     ) -> List[NotificationRecord]:
#         pass

#     @abstractmethod
#     async def get_notification_count(
#         self,
#         user_id: str,
#         status: Optional[NotificationStatus] = None,
#         channel_type: Optional[str] = None,
#     ) -> int:
#         """Get count of notifications for a user with optional status filtering"""
#         pass


class MongoDBNotificationStorage:
    """Notification storage — delegates persistence to notification_repository."""

    async def save_notification(self, notification: NotificationRecord) -> None:
        """Save a notification to MongoDB"""
        await notification_repository.create(notification)

    async def get_notification(
        self, notification_id: str, user_id: str | None
    ) -> NotificationRecord | None:
        """Retrieve a notification by ID with optional user validation"""
        return await notification_repository.get_for_user(notification_id, user_id)

    async def update_notification(self, notification_id: str, updates: dict[str, Any]) -> None:
        """Update a notification's fields"""
        log.set_ns("notification", notification_id=notification_id)
        log.info(
            f"{LogTag.NOTIFICATION} Updating notification {notification_id} with updates: {updates}"
        )
        await notification_repository.update_fields(notification_id, **updates)

    async def get_user_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        channel_type: str | None = None,
        notification_type: NotificationType | None = None,
        source: NotificationSourceEnum | None = None,
    ) -> list[NotificationRecord]:
        """Get user's notifications with optional filtering"""
        return await notification_repository.list_for_user(
            user_id,
            status=status,
            channel_type=channel_type,
            notification_type=notification_type,
            source=source,
            limit=limit,
            offset=offset,
        )

    async def get_notification_count(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
    ) -> int:
        """Get count of notifications for a user with optional status filtering"""
        return await notification_repository.count_for_user(
            user_id, status=status, channel_type=channel_type
        )
