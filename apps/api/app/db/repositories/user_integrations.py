"""Repository for the ``user_integrations`` collection.

User-scoped; one document per ``(user_id, integration_id)`` (unique index),
addressed by the business ``integration_id`` within a user. Tracks which
integrations a user has added and whether they are connected.
"""

from datetime import UTC, datetime

from app.db.repositories.base import UserScopedRepository
from app.models.integration_models import (
    UserIntegrationDocument,
    UserIntegrationStatus,
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

    async def is_expired(self, user_id: str, integration_id: str) -> bool:
        """Whether a *dead* connection is why this is unusable, rather than one
        that was never set up. The stored record is the only thing that tells the
        two apart — a live status check just says "not usable"."""
        doc = await self.get_for_user(user_id, integration_id)
        return doc is not None and doc.status == "expired"

    async def set_status(
        self,
        user_id: str,
        integration_id: str,
        *,
        status: UserIntegrationStatus,
        expired_reason: str | None = None,
        connected_account_id: str | None = None,
    ) -> bool:
        """Upsert the user's connection status. ``connected_at`` is stamped on the
        connected transition and ``expired_at``/``expired_reason`` on the expired one;
        ``created_at`` only on insert. ``connected_account_id`` is written whenever
        the caller learns it and never cleared — the id of the account that died is
        what lets us address it after the fact. Reconnecting clears the expiry stamps so an
        `expired` record never reads as connected-but-broken. Always succeeds (the
        upsert matches or inserts), matching the old modified/upserted/matched check."""
        set_fields: dict[str, object] = {
            "status": status,
            "user_id": user_id,
            "integration_id": integration_id,
        }
        if connected_account_id is not None:
            set_fields["connected_account_id"] = connected_account_id
        if status == "connected":
            set_fields["connected_at"] = datetime.now(UTC)
            set_fields["expired_at"] = None
            set_fields["expired_reason"] = None
        elif status == "expired":
            set_fields["expired_at"] = datetime.now(UTC)
            set_fields["expired_reason"] = expired_reason
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
