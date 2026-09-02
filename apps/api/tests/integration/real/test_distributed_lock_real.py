"""``DistributedLock`` against real Redis.

Only real Redis proves this: the lock is a SET NX lease with a token-checked Lua
release, and the properties under test are what happens to that lease *over
time* — two processes must never hold it at once, a holder still working within
its budget must keep it via the watchdog, and a holder wedged past the max-hold
cap must be forcibly evicted so it can't freeze the system forever.

These are the guarantees ``run_idempotent`` leans on to stop a cold-start replica
herd from each re-embedding the whole tool catalog: the herd serializes on the
lease, and a follower that acquires after the leader finishes re-runs the
now-empty diff instead of racing it.
"""

from __future__ import annotations

import asyncio

import pytest

from app.utils.redis_lock import DistributedLock

LOCK_KEY = "test:distributed-lock"


def _lock(**overrides) -> DistributedLock:
    timing = {
        "lease_seconds": 30,
        "acquire_timeout_seconds": 10,
        "renew_seconds": 10,
        "max_hold_seconds": 300,
    }
    timing.update(overrides)
    return DistributedLock(LOCK_KEY, **timing)


@pytest.mark.service
class TestDistributedLock:
    async def test_two_holders_do_not_overlap(self, real_redis) -> None:
        """A second holder of the same key must wait for the first to release."""
        order: list[str] = []

        async def hold(tag: str, work_seconds: float) -> None:
            async with _lock().hold() as held:
                assert held is True
                order.append(f"{tag}:enter")
                await asyncio.sleep(work_seconds)
                order.append(f"{tag}:exit")

        a = asyncio.create_task(hold("A", 0.6))
        await asyncio.sleep(0.1)  # ensure A acquires first
        b = asyncio.create_task(hold("B", 0.1))
        await asyncio.gather(a, b)

        assert order == ["A:enter", "A:exit", "B:enter", "B:exit"]

    async def test_holder_keeps_lease_past_ttl(self, real_redis) -> None:
        """A holder still working within its budget keeps the lease via renewal.

        Lease is 1s but max-hold is generous, so the watchdog renews and the
        waiter must not enter while the holder is still inside.
        """
        overlap = False
        holder_inside = False

        async def holder() -> None:
            nonlocal holder_inside
            async with _lock(
                lease_seconds=1, renew_seconds=0.3, max_hold_seconds=30
            ).hold() as held:
                assert held is True
                holder_inside = True
                await asyncio.sleep(2.0)  # twice the lease TTL, well under max-hold
                holder_inside = False

        async def waiter() -> None:
            nonlocal overlap
            await asyncio.sleep(0.2)
            async with _lock(
                lease_seconds=1, renew_seconds=0.3, max_hold_seconds=30
            ).hold() as held:
                assert held is True
                if holder_inside:
                    overlap = True

        await asyncio.gather(holder(), waiter())
        assert overlap is False

    async def test_wedged_holder_is_evicted_after_max_hold(self, real_redis) -> None:
        """A holder that runs past max-hold loses the lease so it can't block forever.

        The watchdog stops renewing at the cap and the lease lapses within one
        more lease window; a waiter then acquires WHILE the wedged holder is still
        inside its critical section — the forced eviction that keeps a corrupted
        run from freezing the system.
        """
        evicted_while_holder_inside = False
        holder_inside = False

        async def wedged_holder() -> None:
            nonlocal holder_inside
            # max_hold == lease: renewal is capped almost immediately, so the lease
            # expires ~one lease after acquire even though this holds much longer.
            async with _lock(lease_seconds=1, renew_seconds=0.3, max_hold_seconds=1).hold() as held:
                assert held is True
                holder_inside = True
                await asyncio.sleep(4.0)
                holder_inside = False

        async def waiter() -> None:
            nonlocal evicted_while_holder_inside
            await asyncio.sleep(0.2)
            async with _lock(
                lease_seconds=1, acquire_timeout_seconds=5, renew_seconds=0.3
            ).hold() as held:
                assert held is True
                if holder_inside:
                    evicted_while_holder_inside = True

        await asyncio.gather(wedged_holder(), waiter())
        assert evicted_while_holder_inside is True

    async def test_yields_false_when_contended_past_acquire_window(self, real_redis) -> None:
        """A waiter that can't get the lease within its window yields False."""
        got: list[bool] = []

        async def holder() -> None:
            async with _lock().hold() as held:
                assert held is True
                await asyncio.sleep(0.6)

        async def waiter() -> None:
            await asyncio.sleep(0.1)
            # acquire window shorter than the holder's work → gives up
            async with _lock(acquire_timeout_seconds=0.2).hold() as held:
                got.append(held)

        await asyncio.gather(holder(), waiter())
        assert got == [False]

    async def test_run_idempotent_serializes_the_herd(self, real_redis) -> None:
        """Concurrent idempotent runs on one key never overlap their work."""
        order: list[str] = []

        async def work(tag: str) -> None:
            order.append(f"{tag}:enter")
            await asyncio.sleep(0.3)
            order.append(f"{tag}:exit")

        a = asyncio.create_task(_lock().run_idempotent(lambda: work("A")))
        await asyncio.sleep(0.05)
        b = asyncio.create_task(_lock().run_idempotent(lambda: work("B")))
        await asyncio.gather(a, b)

        # Both ran, and neither's critical section interleaved with the other's.
        assert order == ["A:enter", "A:exit", "B:enter", "B:exit"]
