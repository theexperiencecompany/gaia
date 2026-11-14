"""Repository for the device_tokens collection: Expo push tokens, one document per token.

User-scoped and keyed by the token itself under a unique index. A token follows
its device, so registering it again moves it to whoever is signed in there now.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.db.repositories.base import UserScopedRepository
from app.models.device_token_models import DeviceTokenDocument, DeviceTokenUpdate, PlatformType


class DeviceTokensRepository(UserScopedRepository[DeviceTokenDocument, DeviceTokenUpdate]):
    collection_name = "device_tokens"
    document_model = DeviceTokenDocument
    update_model = DeviceTokenUpdate
    uses_object_id = True
    identity_field = "token"
    cache_policy = None

    async def register(
        self, *, user_id: str, token: str, platform: PlatformType, device_id: str | None
    ) -> bool:
        """Put an active token on this user, taking it from any previous holder; True when it is new."""
        token_filter = self._identity_filter(token)
        claim: dict[str, Mapping[str, object]] = {
            "$set": {
                "user_id": user_id,
                "platform": platform.value,
                "device_id": device_id,
                "is_active": True,
            },
            "$setOnInsert": {"created_at": datetime.now(UTC)},
        }
        # pragma: no mutate start — with cache_policy None no cache reads scope; mutmut cannot
        # pragma a single argument.
        matched = await self._apply_raw_update_unfetched(
            token_filter, claim, scope=user_id, upsert=True
        )
        # pragma: no mutate end
        return matched == 0

    async def list_active_tokens(self, user_id: str) -> list[str]:
        """Every active token this user holds; reads the token field alone, as a push needs nothing else."""
        return await self._distinct("token", {"user_id": user_id, "is_active": True})

    async def deactivate(self, tokens: Sequence[str]) -> None:
        """Mark tokens inactive, whoever holds them, so list_active_tokens stops returning them."""
        await self._raw_collection().update_many(
            {"token": {"$in": list(tokens)}}, {"$set": {"is_active": False}}
        )


device_token_repository = DeviceTokensRepository()
