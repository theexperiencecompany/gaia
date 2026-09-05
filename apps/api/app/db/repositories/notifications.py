"""Repository for the notifications collection.

Identity is the UUID ``id`` field, not Mongo's ``_id`` — updates and lookups key
on it. Updates are free-form field patches (an action result may set arbitrary
fields), so they go through ``update_fields`` rather than a rigid update model.
"""

from datetime import datetime

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.notification.notification_models import (
    NotificationFilters,
    NotificationRecord,
    NotificationStatus,
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

    async def list_stale_unread_by_kind(
        self, *, kind: str, older_than: datetime, limit: int
    ) -> list[NotificationRecord]:
        """Unread notifications of ``kind`` created before ``older_than`` that have
        not yet had an ignore-strike recorded — all users (the maintenance sweep's
        scan set for ignored urgent alerts)."""
        return await self._find(
            {
                "original_request.metadata.kind": kind,
                "original_request.metadata.strike_recorded": {"$ne": True},
                "status": {"$ne": NotificationStatus.READ.value},
                "created_at": {"$lt": older_than},
            },
            limit=limit,
        )

    async def mark_strike_recorded(self, notification_id: str) -> None:
        """Stamp that the ignore-strike for this notification was written, so a
        sweep never double-counts it."""
        await self.update_fields(
            notification_id, **{"original_request.metadata.strike_recorded": True}
        )

    async def update_fields(self, notification_id: str, **fields: object) -> None:
        """Apply a free-form field patch. ``updated_at`` is auto-stamped by the base."""
        await self._apply_raw_update(
            {"id": notification_id},
            {"$set": dict(fields)},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def list_for_user(
        self, user_id: str, *, filters: NotificationFilters, limit: int = 50, offset: int = 0
    ) -> list[NotificationRecord]:
        return await self._find(
            self._user_filter(user_id, filters),
            sort=[("created_at", -1)],
            limit=limit,
            skip=offset,
        )

    async def count_for_user(self, user_id: str, *, filters: NotificationFilters) -> int:
        return await self._count(self._user_filter(user_id, filters))

    def _user_filter(self, user_id: str, filters: NotificationFilters) -> dict[str, object]:
        filter_: dict[str, object] = {"user_id": user_id}
        if filters.status is not None:
            filter_["status"] = filters.status
        if filters.channel_type is not None:
            filter_["channels.channel_type"] = filters.channel_type
        if filters.notification_type is not None:
            filter_["original_request.type"] = filters.notification_type.value
        if filters.source is not None:
            filter_["original_request.source"] = filters.source.value
        return filter_


notification_repository = NotificationRepository()
