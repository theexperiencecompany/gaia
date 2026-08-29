"""Hermetic unit tests for ``DistributedLock`` (no real Redis).

The load-bearing concurrency properties — mutual exclusion across processes,
watchdog renewal past the lease TTL, and the max-hold cap that evicts a wedged
holder — are proven against real Redis in
``tests/integration/real/test_distributed_lock_real.py``. Here we pin the
config guard and the degradation contract that must hold with no reachable Redis
at all: a lease that cannot be taken never raises out of the primitive, and
``run_idempotent`` still runs its work rather than skipping it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.utils import redis_lock
from app.utils.redis_lock import DistributedLock

TIMING = {
    "lease_seconds": 30,
    "acquire_timeout_seconds": 1,
    "renew_seconds": 10,
    "max_hold_seconds": 300,
}


def _mock_lock(*, acquire):
    """A redis client whose ``.lock(...)`` returns a lock with the given acquire.

    ``acquire`` is a bool the mock returns, or an exception the mock raises.
    """
    lock = MagicMock()
    if isinstance(acquire, BaseException):
        lock.acquire = AsyncMock(side_effect=acquire)
    else:
        lock.acquire = AsyncMock(return_value=acquire)
    lock.extend = AsyncMock()
    lock.release = AsyncMock()
    client = MagicMock()
    client.lock.return_value = lock
    return client, lock


@pytest.mark.unit
class TestConfigGuard:
    def test_max_hold_below_lease_is_rejected(self):
        # A cap below one lease would evict every holder before its first renewal.
        with pytest.raises(ValueError, match="max_hold_seconds"):
            DistributedLock(
                "k",
                lease_seconds=30,
                acquire_timeout_seconds=1,
                renew_seconds=10,
                max_hold_seconds=5,
            )


@pytest.mark.unit
@pytest.mark.asyncio
class TestHold:
    async def test_yields_false_when_redis_unconfigured(self):
        with patch.object(redis_lock.redis_cache, "redis", None):
            async with DistributedLock("k", **TIMING).hold() as held:
                assert held is False

    async def test_yields_false_when_acquire_raises_connection_error(self):
        client, lock = _mock_lock(acquire=RedisConnectionError("redis down"))
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with DistributedLock("k", **TIMING).hold() as held:
                assert held is False
        # Never acquired → must not attempt a release (would free another holder).
        lock.release.assert_not_called()

    async def test_yields_false_on_acquire_timeout(self):
        client, _lock = _mock_lock(acquire=False)  # blocking_timeout elapsed
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with DistributedLock("k", **TIMING).hold() as held:
                assert held is False

    async def test_holds_then_releases_when_acquired(self):
        client, lock = _mock_lock(acquire=True)
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with DistributedLock("k", **TIMING).hold() as held:
                assert held is True
        lock.release.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
class TestRunIdempotent:
    async def test_runs_work_when_redis_unconfigured(self):
        ran = []

        async def work():
            ran.append(1)

        with patch.object(redis_lock.redis_cache, "redis", None):
            await DistributedLock("k", **TIMING).run_idempotent(work)
        assert ran == [1]

    async def test_runs_work_under_the_lease_when_held(self):
        client, lock = _mock_lock(acquire=True)
        ran = []

        async def work():
            ran.append(1)

        with patch.object(redis_lock.redis_cache, "redis", client):
            await DistributedLock("k", **TIMING).run_idempotent(work)
        assert ran == [1]
        lock.release.assert_awaited_once()

    async def test_work_error_is_not_swallowed(self):
        # A failure inside the work is the caller's bug, not the lock's to hide —
        # even on the degraded (no-Redis) path.
        async def work():
            raise ValueError("boom")

        with patch.object(redis_lock.redis_cache, "redis", None):
            with pytest.raises(ValueError, match="boom"):
                await DistributedLock("k", **TIMING).run_idempotent(work)
