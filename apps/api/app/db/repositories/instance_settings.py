"""Repository for the ``instance_settings`` collection — instance-wide key/value state.

Single document per logical setting (``key="secrets"`` holds the generated
instance secret, ``key="setup"`` the setup wizard's progress). Keyed by the
business ``key`` field; writes are upserts. No cache: reads are rare (secret
derivation, setup checks) and must always observe the latest persisted value.
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
        """The single document stored under ``key``, or ``None``."""
        return await self._find_one({"key": key})

    async def upsert_value(self, key: str, value: dict[str, object]) -> InstanceSettingsDocument:
        """Insert or replace the value under ``key`` and return the stored doc."""
        doc = await self._apply_raw_update(
            {"key": key},
            {"$set": {"value": value}},
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )
        if doc is None:
            raise AppError(
                message=f"instance_settings upsert for key '{key}' returned no document",
                why="an upsert with return_document=AFTER always yields the stored row",
                fix="check Mongo connectivity / collection write permissions",
            )
        return doc

    async def set_if_absent(self, key: str, value: dict[str, object]) -> bool:
        """Atomically insert ``value`` only when ``key`` does not exist yet.

        Returns True when this call's value won the insert. Losers of a
        concurrent insert leave the winner's value untouched — the caller must
        re-read instead of assuming its own value was stored.
        """
        result = await self._raw_collection().update_one(
            {"key": key},
            {"$setOnInsert": {"key": key, "value": value}},
            upsert=True,
        )
        return result.upserted_id is not None


instance_settings_repository = InstanceSettingsRepository()
