"""Repository for the scouts collection: one document per (user, connected integration)."""

from collections.abc import Mapping

from app.db.repositories.base import UserScopedRepository
from app.models.scout_models import ScoutDocument, ScoutUpdate


class ScoutsRepository(UserScopedRepository[ScoutDocument, ScoutUpdate]):
    collection_name = "scouts"
    document_model = ScoutDocument
    update_model = ScoutUpdate
    uses_object_id = True
    cache_policy = None

    async def find_for(self, user_id: str, integration_id: str) -> ScoutDocument | None:
        return await self._find_one({"user_id": user_id, "integration_id": integration_id})

    async def replace(self, scout: ScoutDocument) -> None:
        """Store scout as the user's one scout for its integration, replacing any earlier one."""
        key = {"user_id": scout.user_id, "integration_id": scout.integration_id}
        update: dict[str, Mapping[str, object]] = {"$set": scout.model_dump(exclude={"id"})}
        # pragma: no mutate start — with cache_policy None, scope addresses no cache;
        # mutmut cannot pragma a single argument.
        await self._apply_raw_update_unfetched(key, update, scope=scout.user_id, upsert=True)
        # pragma: no mutate end

    async def delete_for(self, user_id: str, integration_id: str) -> int:
        key = {"user_id": user_id, "integration_id": integration_id}
        # pragma: no mutate start — with cache_policy None, scope addresses no cache.
        return await self._delete_many(key, scope=user_id)
        # pragma: no mutate end


scouts_repository = ScoutsRepository()
