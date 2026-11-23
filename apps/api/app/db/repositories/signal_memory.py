"""Repository for signal_memory: what the brief remembers about each item it has seen."""

from collections.abc import Sequence
from datetime import datetime

from pymongo import UpdateOne

from app.db.repositories.base import UserScopedRepository
from app.models.scout_models import Sighted, SignalMemoryDocument, SignalMemoryUpdate


def _key(signal: Sighted) -> dict[str, object]:
    return {"integration_id": signal.integration_id, "external_id": signal.external_id}


class SignalMemoryRepository(UserScopedRepository[SignalMemoryDocument, SignalMemoryUpdate]):
    collection_name = "signal_memory"
    document_model = SignalMemoryDocument
    update_model = SignalMemoryUpdate
    uses_object_id = True
    cache_policy = None

    async def find_for(
        self, user_id: str, signals: Sequence[Sighted]
    ) -> list[SignalMemoryDocument]:
        if not signals:
            return []
        return await self._find({"user_id": user_id, "$or": [_key(s) for s in signals]})

    async def record_seen(self, user_id: str, signals: Sequence[Sighted], at: datetime) -> None:
        """Remember each signal's state as of at, in one unordered write; a first sighting stamps first_seen."""
        if not signals:
            return
        await self._raw_collection().bulk_write(
            [
                UpdateOne(
                    {"user_id": user_id, **_key(signal)},
                    {
                        "$set": {"last_state": signal.state, "last_seen": at},
                        "$setOnInsert": {"first_seen": at},
                    },
                    upsert=True,
                )
                for signal in signals
            ],
            ordered=False,
        )

    async def mark_shown(self, user_id: str, signals: Sequence[Sighted], at: datetime) -> None:
        if not signals:
            return
        await self._raw_collection().update_many(
            {"user_id": user_id, "$or": [_key(s) for s in signals]},
            {"$inc": {"times_shown": 1}, "$set": {"last_shown": at}},
        )

    async def delete_for_integration(self, user_id: str, integration_id: str) -> int:
        key = {"user_id": user_id, "integration_id": integration_id}
        return await self._delete_many(key)


signal_memory_repository = SignalMemoryRepository()
