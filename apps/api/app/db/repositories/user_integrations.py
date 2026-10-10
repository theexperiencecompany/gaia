"""Repository for the user_integrations collection.

User-scoped; one document per (user_id, integration_id) (unique index),
addressed by the business integration_id within a user. Tracks which
integrations a user has added and whether they are connected.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.constants.cache import USER_INTEGRATION_CACHE_PREFIX
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.integration_models import (
    IntegrationAccount,
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
    # Read on every tool call and trigger event (which account a call or event is);
    # every write here goes through the base, which bumps the user's generation.
    cache_policy = CachePolicy(prefix=USER_INTEGRATION_CACHE_PREFIX)

    @cached_query(UserIntegrationDocument)
    async def get_for_user(
        self, user_id: str, integration_id: str
    ) -> UserIntegrationDocument | None:
        return await self._find_one({"user_id": user_id, "integration_id": integration_id})

    @cached_query(list[UserIntegrationDocument])
    async def list_for_user(
        self,
        user_id: str,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[UserIntegrationDocument]:
        return await super().list_for_user(user_id, sort=sort, limit=limit, skip=skip)

    async def exists(self, user_id: str, integration_id: str) -> bool:
        return await self.get_for_user(user_id, integration_id) is not None

    async def list_for_user_newest_first(self, user_id: str) -> list[UserIntegrationDocument]:
        return await self.list_for_user(user_id, sort=[("created_at", -1)])

    async def delete_for_user(self, user_id: str, integration_id: str) -> bool:
        return await self.delete(integration_id, user_id=user_id)

    async def is_connected(self, user_id: str, integration_id: str) -> bool:
        doc = await self.get_for_user(user_id, integration_id)
        return doc is not None and doc.status == "connected"

    async def has_connected_before(self, user_id: str, integration_id: str) -> bool:
        """Whether this user's record was ever connected; connected_at survives a later expiry or re-auth."""
        doc = await self.get_for_user(user_id, integration_id)
        return doc is not None and doc.connected_at is not None

    async def is_expired(self, user_id: str, integration_id: str) -> bool:
        """Whether a *dead* connection, not one never set up, is why this is unusable.

        The stored record is the only thing that tells the two apart — a live
        status check just says "not usable".
        """
        doc = await self.get_for_user(user_id, integration_id)
        return doc is not None and doc.status == "expired"

    async def set_status(
        self,
        user_id: str,
        integration_id: str,
        *,
        status: UserIntegrationStatus,
        expired_reason: str | None = None,
    ) -> bool:
        """Upsert the user's connection status; always succeeds (the upsert matches or inserts).

        connected_at/expired_at/expired_reason stamp on their transitions;
        reconnecting clears the expiry stamps.
        """
        set_fields: dict[str, object] = {
            "status": status,
            "user_id": user_id,
            "integration_id": integration_id,
        }
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

    async def save_accounts(
        self,
        user_id: str,
        integration_id: str,
        *,
        accounts: list[IntegrationAccount],
        primary_account_id: str | None,
        status: UserIntegrationStatus,
        expired_reason: str | None = None,
    ) -> UserIntegrationDocument:
        """Replace the account list and primary, with the status derived from them, in one write.

        Status stamps follow set_status: connected clears the expiry, expired records it.
        """
        now = datetime.now(UTC)
        set_fields: dict[str, object] = {
            "user_id": user_id,
            "integration_id": integration_id,
            "accounts": [a.model_dump() for a in accounts],
            "primary_account_id": primary_account_id,
            "status": status,
        }
        if status == "connected":
            set_fields["connected_at"] = now
            set_fields["expired_at"] = None
            set_fields["expired_reason"] = None
        elif status == "expired":
            set_fields["expired_at"] = now
            set_fields["expired_reason"] = expired_reason
        doc = await self._apply_raw_update(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": set_fields, "$setOnInsert": {"created_at": now}},
            scope=user_id,
            upsert=True,
        )
        if doc is None:
            raise RuntimeError(f"user_integrations upsert returned nothing for {integration_id}")
        return doc

    async def set_account_nickname(
        self, user_id: str, integration_id: str, account_id: str, nickname: str | None
    ) -> UserIntegrationDocument | None:
        """Name one account in place, so concurrent writes to other accounts survive; None when absent."""
        return await self._apply_raw_update(
            {
                "user_id": user_id,
                "integration_id": integration_id,
                "accounts.id": account_id,
            },
            {"$set": {"accounts.$[account].nickname": nickname}},
            scope=user_id,
            array_filters=[{"account.id": account_id}],
        )

    async def replace_legacy_account(
        self,
        user_id: str,
        integration_id: str,
        *,
        accounts: list[IntegrationAccount],
        primary_account_id: str | None,
        status: UserIntegrationStatus,
    ) -> UserIntegrationDocument | None:
        """Move a pre-multi-account record onto its account list, dropping its single account id."""
        return await self._apply_raw_update(
            {"user_id": user_id, "integration_id": integration_id},
            {
                "$set": {
                    "accounts": [a.model_dump() for a in accounts],
                    "primary_account_id": primary_account_id,
                    "status": status,
                },
                "$unset": {"connected_account_id": ""},
            },
            scope=user_id,
        )

    async def user_ids_with_integration(self, integration_id: str) -> list[str]:
        """Every user_id that has added integration_id (cross-user fan-out for cache-bust/cleanup)."""
        return await self._distinct("user_id", {"integration_id": integration_id})


user_integration_repository = UserIntegrationsRepository()
