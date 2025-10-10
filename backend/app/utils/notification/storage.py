from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import (
    notifications_collection,
)
from app.models.notification.notification_models import (
    NotificationRecord,
    NotificationStatus,
    NotificationType,
    NotificationSourceEnum,
)

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
    """MongoDB storage implementation for notifications"""

    async def save_notification(self, notification: NotificationRecord) -> None:
        """Save a notification to MongoDB"""
        await notifications_collection.insert_one(notification.model_dump())

    async def get_notification(
        self, notification_id: str, user_id: str | None
    ) -> Optional[NotificationRecord]:
        """Retrieve a notification by ID with optional user validation"""
        query = {"id": notification_id}
        if user_id is not None:
            query["user_id"] = user_id

        result = await notifications_collection.find_one(query)
        if result:
            return NotificationRecord.model_validate(result)
        return None

    async def update_notification(
        self, notification_id: str, updates: Dict[str, Any]
    ) -> None:
        """Update a notification's fields"""
        updates["updated_at"] = datetime.now(timezone.utc)

        # Debug logging
        logger.info(f"Updating notification {notification_id} with updates: {updates}")

        result = await notifications_collection.update_one(
            {"id": notification_id}, {"$set": updates}
        )

        # Log the result
        logger.info(
            f"Update result - matched: {result.matched_count}, modified: {result.modified_count}"
        )

        if result.matched_count == 0:
            logger.warning(f"No notification found with id: {notification_id}")
        elif result.modified_count == 0:
            logger.warning(f"Notification {notification_id} found but not modified")
        else:
            logger.info(f"Successfully updated notification {notification_id}")

    async def get_user_notifications(
        self,
        user_id: str,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0,
        channel_type: Optional[str] = None,
        notification_type: Optional[NotificationType] = None,
        source: Optional[NotificationSourceEnum] = None,
    ) -> List[NotificationRecord]:
        """Get user's notifications with optional filtering"""
        query = {"user_id": user_id}
        if status is not None:
            query["status"] = status

        # Filter by channel type if specified
        if channel_type is not None:
            query["channels.channel_type"] = channel_type

        # Filter by notification type if specified
        if notification_type is not None:
            query["notification_type"] = notification_type

        # Filter by source if specified
        if source is not None:
            query["source"] = source

        cursor = notifications_collection.find(query)
        cursor = cursor.sort("created_at", -1).skip(offset).limit(limit)

        results = await cursor.to_list(length=limit)
        return [NotificationRecord.model_validate(doc) for doc in results]

    async def get_notification_count(
        self,
        user_id: str,
        status: Optional[NotificationStatus] = None,
        channel_type: Optional[str] = None,
    ) -> int:
        """Get count of notifications for a user with optional status filtering"""
        query = {"user_id": user_id}
        if status is not None:
            query["status"] = status
        if channel_type is not None:
            query["channels.channel_type"] = channel_type

        return await notifications_collection.count_documents(query)
