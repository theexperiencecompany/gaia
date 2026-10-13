"""Repository for the notifications collection.

Identity is the UUID id field, not Mongo's _id — updates and lookups key
on it. Updates are free-form field patches (an action result may set arbitrary
fields), so they go through update_fields rather than a rigid update model.
"""

from datetime import UTC, datetime

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.base import MongoRepository
from app.models.notification.notification_models import (
    NotificationListFilters,
    NotificationRecord,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationUpdate,
)


class NotificationRepository(MongoRepository[NotificationRecord, NotificationUpdate]):
    collection_name = "notifications"
    document_model = NotificationRecord
    update_model = NotificationUpdate
    uses_object_id = True
    identity_field = "id"
    cache_policy = None

    async def get_for_user(
        self, notification_id: str, user_id: str | None
    ) -> NotificationRecord | None:
        filter_: dict[str, object] = {"id": notification_id}
        if user_id is not None:
            filter_["user_id"] = user_id
        return await self._find_one(filter_)

    async def update_fields(self, notification_id: str, **fields: object) -> None:
        """Apply a free-form field patch. updated_at is auto-stamped by the base."""
        await self._apply_raw_update(
            {"id": notification_id},
            {"$set": dict(fields)},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def list_for_user(
        self,
        user_id: str,
        *,
        filters: NotificationListFilters | None = None,
    ) -> list[NotificationRecord]:
        f = filters or NotificationListFilters()
        return await self._find(
            self._user_filter(user_id, f.status, f.channel_type, f.notification_type, f.source),
            sort=[("created_at", -1)],
            limit=f.limit,
            skip=f.offset,
        )

    async def count_for_user(
        self,
        user_id: str,
        *,
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
    ) -> int:
        return await self._count(self._user_filter(user_id, status, channel_type, None, None))

    async def mark_all_read_for_user(self, user_id: str, *, channel_type: str | None = None) -> int:
        """Mark every DELIVERED notification for a user as READ in one write.

        Issues its own update_many (unbounded set; base only exposes single-doc
        updates), so contract fixtures must patch this module's collection
        accessor too. cache_policy is None: no entity cache or generation
        counter to refresh.
        """
        filter_ = self._user_filter(user_id, NotificationStatus.DELIVERED, channel_type, None, None)
        result = await get_async_collection(self.collection_name).update_many(
            filter_,
            {"$set": {"status": NotificationStatus.READ.value, "read_at": datetime.now(UTC)}},
        )
        return int(result.modified_count)

    def _user_filter(
        self,
        user_id: str,
        status: NotificationStatus | None,
        channel_type: str | None,
        notification_type: NotificationType | None,
        source: NotificationSourceEnum | None,
    ) -> dict[str, object]:
        filter_: dict[str, object] = {"user_id": user_id}
        if status is not None:
            filter_["status"] = status
        if channel_type is not None:
            filter_["channels.channel_type"] = channel_type
        if notification_type is not None:
            filter_["original_request.type"] = notification_type.value
        if source is not None:
            filter_["original_request.source"] = source.value
        return filter_


notification_repository = NotificationRepository()
