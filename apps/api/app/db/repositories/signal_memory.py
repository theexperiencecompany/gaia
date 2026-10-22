"""Repository for signal_memory: what the brief remembers about each signal it has seen."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from app.db.repositories.base import UserScopedRepository
from app.models.scout_models import Signal, SignalMemoryDocument, SignalMemoryUpdate


def _key(signal: Signal) -> dict[str, object]:
    return {"integration_id": signal.integration_id, "external_id": signal.external_id}


class SignalMemoryRepository(UserScopedRepository[SignalMemoryDocument, SignalMemoryUpdate]):
    collection_name = "signal_memory"
    document_model = SignalMemoryDocument
    update_model = SignalMemoryUpdate
    uses_object_id = True
    cache_policy = None

    async def find_for(self, user_id: str, signals: Sequence[Signal]) -> list[SignalMemoryDocument]:
        if not signals:
            return []
        return await self._find({"user_id": user_id, "$or": [_key(s) for s in signals]})

    async def record_seen(self, user_id: str, signals: Sequence[Signal], at: datetime) -> None:
        """Remember each signal's state as of now; the first sighting also stamps first_seen."""
        for signal in signals:
            key = {"user_id": user_id, **_key(signal)}
            update: dict[str, Mapping[str, object]] = {
                "$set": {"last_state": signal.state},
                "$setOnInsert": {"first_seen": at},
            }
            # pragma: no mutate start — with cache_policy None, scope addresses no cache;
            # mutmut cannot pragma a single argument.
            await self._apply_raw_update_unfetched(key, update, scope=user_id, upsert=True)
            # pragma: no mutate end

    async def mark_shown(self, user_id: str, signals: Sequence[Signal], at: datetime) -> None:
        if not signals:
            return
        await self._raw_collection().update_many(
            {"user_id": user_id, "$or": [_key(s) for s in signals]},
            {"$inc": {"times_shown": 1}, "$set": {"last_shown": at}},
        )

    async def delete_for_integration(self, user_id: str, integration_id: str) -> int:
        key = {"user_id": user_id, "integration_id": integration_id}
        # pragma: no mutate start — with cache_policy None, scope addresses no cache.
        return await self._delete_many(key, scope=user_id)
        # pragma: no mutate end


signal_memory_repository = SignalMemoryRepository()
