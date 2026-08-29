"""Cross-replica sandbox acquisition lock, against real Redis.

Only real Redis proves this: the lock is a SET NX lease with a token-checked Lua
release, and the property under test is what happens to that lease *over time*.

The bug this pins: the lease used to be a flat 30s with no renewal, so a holder
still inside the critical section at 30s silently lost it and a second replica
walked in — the exact concurrent create the lock exists to prevent. The critical
section can legitimately run for minutes (a cold E2B create plus the JuiceFS
mount script), so this was reachable in normal use, not a contrived race.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.sandbox import pool as pool_module
from app.services.sandbox.errors import SandboxAcquisitionError
from app.services.sandbox.pool import SANDBOX_LOCK_KEY_PREFIX, SandboxPool


@pytest.fixture
def fast_lease(monkeypatch):
    """Shrink the lease so renewal is observable in ~2s instead of ~90s."""
    monkeypatch.setattr(pool_module, "SANDBOX_LOCK_LEASE_SECONDS", 1)
    monkeypatch.setattr(pool_module, "SANDBOX_LOCK_RENEW_SECONDS", 0.3)


@pytest.mark.service
class TestSandboxDistributedLock:
    async def test_second_replica_waits_for_the_first(self, real_redis) -> None:
        """Two pools (two replicas) must not hold the same user's lock at once."""
        user_id = "lock-user-serialize"
        order: list[str] = []

        async def hold(pool: SandboxPool, tag: str, seconds: float) -> None:
            async with pool.distributed_lock(user_id):
                order.append(f"{tag}:enter")
                await asyncio.sleep(seconds)
                order.append(f"{tag}:exit")

        first, second = SandboxPool(), SandboxPool()
        a = asyncio.create_task(hold(first, "A", 0.6))
        await asyncio.sleep(0.1)
        b = asyncio.create_task(hold(second, "B", 0.1))
        await asyncio.gather(a, b)

        assert order == ["A:enter", "A:exit", "B:enter", "B:exit"]

    async def test_holder_keeps_the_lease_past_its_ttl(self, real_redis, fast_lease) -> None:
        """A holder still working after the lease expires must not be displaced.

        Without renewal the waiter enters at ~1s while the holder is still
        inside, and both are in the critical section at once.
        """
        user_id = "lock-user-renew"
        overlap = False

        async def holder(pool: SandboxPool) -> None:
            async with pool.distributed_lock(user_id):
                await asyncio.sleep(2.5)  # 2.5x the lease
                nonlocal overlap
                overlap = waiter_entered

        waiter_entered = False

        async def waiter(pool: SandboxPool) -> None:
            await asyncio.sleep(0.2)
            async with pool.distributed_lock(user_id):
                nonlocal waiter_entered
                waiter_entered = True

        await asyncio.gather(holder(SandboxPool()), waiter(SandboxPool()))

        assert overlap is False, "a second replica entered while the holder was still inside"

    async def test_lease_is_released_when_the_block_exits(self, real_redis) -> None:
        pool = SandboxPool()
        user_id = "lock-user-release"
        async with pool.distributed_lock(user_id):
            assert await real_redis.exists(f"{SANDBOX_LOCK_KEY_PREFIX}{user_id}")
        assert not await real_redis.exists(f"{SANDBOX_LOCK_KEY_PREFIX}{user_id}")

    async def test_lease_expires_when_a_replica_dies_holding_it(
        self, real_redis, fast_lease
    ) -> None:
        """A pod killed mid-acquire must free the user, not wedge them until a deploy.

        Simulated by taking the lease and never releasing it — which is exactly
        what a SIGKILL leaves behind, since no finally block runs.
        """
        user_id = "lock-user-crash"
        abandoned = real_redis.lock(
            f"{SANDBOX_LOCK_KEY_PREFIX}{user_id}",
            timeout=pool_module.SANDBOX_LOCK_LEASE_SECONDS,
            thread_local=False,
        )
        assert await abandoned.acquire(blocking=False)

        # No renewal is running, so the lease lapses and the next replica proceeds.
        async with SandboxPool().distributed_lock(user_id):
            pass

    async def test_waiting_out_the_acquire_timeout_raises(self, real_redis, monkeypatch) -> None:
        """Never proceed unlocked — an unserialized create is the bug, not the fallback."""
        monkeypatch.setattr(pool_module, "SANDBOX_LOCK_ACQUIRE_TIMEOUT_SECONDS", 0.3)
        user_id = "lock-user-timeout"

        async with SandboxPool().distributed_lock(user_id):
            with pytest.raises(SandboxAcquisitionError, match="held it past the wait window"):
                async with SandboxPool().distributed_lock(user_id):
                    pass

    async def test_missing_redis_raises_instead_of_running_unserialized(self, monkeypatch) -> None:
        from app.db.redis import redis_cache

        monkeypatch.setattr(redis_cache, "redis", None)
        with pytest.raises(SandboxAcquisitionError, match="Redis is unavailable"):
            async with SandboxPool().distributed_lock("lock-user-noredis"):
                pass
