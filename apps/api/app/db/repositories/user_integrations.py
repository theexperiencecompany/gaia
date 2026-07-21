"""Repository for the ``user_integrations`` collection.

User-scoped; one document per ``(user_id, integration_id)`` (unique index),
addressed by the business ``integration_id`` within a user. Tracks which
integrations a user has added and whether they are connected.
"""

from datetime import UTC, datetime
from typing import Literal

from app.db.repositories.base import UserScopedRepository
from app.models.integration_models import (
    UserIntegrationDocument,
    UserIntegrationUpdate,
)


class UserIntegrationsRepository(
    UserScopedRepository[UserIntegrationDocument, UserIntegrationUpdate]
):
    collection_name = "user_integrations"
    document_model = UserIntegrationDocument
    update_model = UserIntegrationUpdate
    uses_object_id = True
    identity_field = "integration_id"
    cache_policy = None

    async def get_for_user(
        self, user_id: str, integration_id: str
    ) -> UserIntegrationDocument | None:
        return await self._find_one({"user_id": user_id, "integration_id": integration_id})

    async def exists(self, user_id: str, integration_id: str) -> bool:
        return await self.get_for_user(user_id, integration_id) is not None

    async def list_for_user_newest_first(self, user_id: str) -> list[UserIntegrationDocument]:
        return await self.list_for_user(user_id, sort=[("created_at", -1)])

    async def delete_for_user(self, user_id: str, integration_id: str) -> bool:
        return await self.delete(integration_id, user_id=user_id)

    async def is_connected(self, user_id: str, integration_id: str) -> bool:
        doc = await self.get_for_user(user_id, integration_id)
        return doc is not None and doc.status == "connected"

    async def set_status(
        self, user_id: str, integration_id: str, *, status: Literal["created", "connected"]
    ) -> bool:
        """Upsert the user's connection status. ``connected_at`` is stamped on the
        connected transition; ``created_at`` only on insert. Always succeeds (the
        upsert matches or inserts), matching the old modified/upserted/matched check."""
        set_fields: dict[str, object] = {
            "status": status,
            "user_id": user_id,
            "integration_id": integration_id,
        }
        if status == "connected":
            set_fields["connected_at"] = datetime.now(UTC)
        doc = await self._apply_raw_update(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": set_fields, "$setOnInsert": {"created_at": datetime.now(UTC)}},
            scope=user_id,
            upsert=True,
        )
        return doc is not None

    async def user_ids_with_integration(self, integration_id: str) -> list[str]:
        """Every user_id that has added ``integration_id`` (cross-user — for the
        cache-bust / link-cleanup fan-out when a shared integration changes)."""
        return await self._distinct("user_id", {"integration_id": integration_id})


user_integration_repository = UserIntegrationsRepository()
