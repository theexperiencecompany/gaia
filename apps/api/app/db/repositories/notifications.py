"""Repository for the notifications collection.

Identity is the UUID ``id`` field, not Mongo's ``_id`` — updates and lookups key
on it. Updates are free-form field patches (an action result may set arbitrary
fields), so they go through ``update_fields`` rather than a rigid update model.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.notification.notification_models import (
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
        """Apply a free-form field patch. ``updated_at`` is auto-stamped by the base."""
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
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
        notification_type: NotificationType | None = None,
        source: NotificationSourceEnum | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationRecord]:
        return await self._find(
            self._user_filter(user_id, status, channel_type, notification_type, source),
            sort=[("created_at", -1)],
            limit=limit,
            skip=offset,
        )

    async def count_for_user(
        self,
        user_id: str,
        *,
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
    ) -> int:
        return await self._count(self._user_filter(user_id, status, channel_type, None, None))

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
