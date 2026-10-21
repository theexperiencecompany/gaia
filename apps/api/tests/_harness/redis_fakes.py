"""One in-memory Redis for the background browser job, keys and streams together.

The job store and the job's card feed share a connection in production, so a
test that drives both through one fake is the only one that can catch them
disagreeing. Faithful where the code depends on it: SET NX refuses an existing
key, EXPIRE only touches a key that exists, and XREAD returns strictly what
follows the cursor, in order.

A blocking XREAD that finds nothing costs its block time on clock, a fake
monotonic clock a test hands to the code that polls: a poller that never meets
its stop condition then reaches its deadline in fake time instead of spinning.
"""

from typing import Any


class FakeRedisClient:
    """The raw client: SET NX / TTL semantics plus a single-consumer stream."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.expire_calls: list[tuple[str, int]] = []
        self.xadd_calls: list[tuple[str, int | None, bool]] = []
        self.xread_calls: list[tuple[dict[str, str], int | None]] = []
        self.clock = 0.0
        self._seq = 0

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            removed += 1 if self.store.pop(name, None) is not None else 0
            self.ttls.pop(name, None)
        return removed

    async def exists(self, *names: str) -> int:
        return sum(1 for name in names if name in self.store)

    async def expire(self, name: str, time: int) -> bool:
        self.expire_calls.append((name, time))
        if name not in self.store and name not in self.streams:
            return False
        self.ttls[name] = time
        return True

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self.xadd_calls.append((name, maxlen, approximate))
        self._seq += 1
        entry_id = f"{self._seq}-0"
        self.streams.setdefault(name, []).append((entry_id, dict(fields)))
        return entry_id

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        self.xread_calls.append((dict(streams), block))
        results: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for name, cursor in streams.items():
            after = [
                entry
                for entry in self.streams.get(name, [])
                if _entry_order(entry[0]) > _entry_order(cursor)
            ]
            if after:
                results.append((name, after))
        if not results and block:
            self.clock += block / 1000
        return results


class FakeRedisCache:
    """The redis_cache facade: model-level get/set/delete over the same store the raw client sees."""

    def __init__(self) -> None:
        self.client = FakeRedisClient()
        self.models: dict[str, Any] = {}
        self.set_calls: list[tuple[str, int | None, type[Any] | None]] = []

    async def get(self, key: str, model: type[Any] | None = None) -> Any:
        return self.models.get(key)

    async def set(
        self, key: str, value: object, ttl: int = 3600, model: type[Any] | None = None
    ) -> bool:
        self.set_calls.append((key, ttl, model))
        self.models[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.models.pop(key, None)
        await self.client.delete(key)


def _entry_order(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)
