"""Repository for the instance_settings collection: instance-wide key/value state.

One document per logical setting (key secrets holds the generated instance
secret, key setup the wizard progress, key composio_auth_configs the admin's
Composio auth config ids). Keyed by the business key field and
written as upserts. No cache: reads are rare and must observe the latest
persisted value.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.runtime_models import InstanceSettingsDocument, InstanceSettingsUpdate
from app.utils.errors import AppError


class InstanceSettingsRepository(MongoRepository[InstanceSettingsDocument, InstanceSettingsUpdate]):
    collection_name = "instance_settings"
    document_model = InstanceSettingsDocument
    update_model = InstanceSettingsUpdate
    uses_object_id = False
    identity_field = "key"
    cache_policy = None

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        """Return the single document stored under key, or None."""
        return await self._find_one({"key": key})

    async def set_value(self, key: str, value: dict[str, object]) -> None:
        """Insert or replace the value stored under key in one round trip."""
        await self._apply_raw_update_unfetched(
            {"key": key},
            {"$set": {"value": value}},
            scope=REPO_GLOBAL_SCOPE,  # pragma: no mutate — a cacheless global repo never reads its scope
            upsert=True,
        )

    async def set_if_absent(self, key: str, value: dict[str, object]) -> bool:
        """Atomically insert value only when key does not exist yet.

        Returns True when this call won the insert. Losers leave the winner's
        value untouched; the caller must re-read instead of assuming its own
        value was stored.
        """
        result = await self._raw_collection().update_one(
            {"key": key},
            {"$setOnInsert": {"key": key, "value": value}},
            upsert=True,
        )
        return result.upserted_id is not None

    async def put(self, key: str, value: dict[str, object]) -> InstanceSettingsDocument:
        """Store value under key, creating the document when absent."""
        stored = await self._apply_raw_update(
            {"key": key},
            {"$set": {"value": value}},
            scope=REPO_GLOBAL_SCOPE,  # pragma: no mutate — a cacheless global repo never reads its scope
            upsert=True,
        )
        if stored is None:
            raise AppError(
                message=f"instance setting {key!r} could not be read back",  # pragma: no mutate — an upsert always reads back its row
            )
        return stored


instance_settings_repository = InstanceSettingsRepository()
