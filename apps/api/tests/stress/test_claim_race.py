"""Stress: race-for-claim on the tracked-todo execution lock.

Real code under test: ``execute_tracked_todo`` in
``app/workers/tasks/tracked_todo_tasks.py`` — every execution claims the todo
with ``SET gaia_todo_exec:{todo_id} 1 NX EX 1800`` and releases it in a
``finally``. Redis is an in-process fake whose ``set`` has no ``await`` between
check and write, mirroring Redis's single-threaded command atomicity, so the
race resolves deterministically: exactly one of N concurrent claims wins.

The double-claims invariant: at most one runner inside the critical section at
a time, losers never release a lock they did not acquire, and the lock is held
until the section completes and released afterwards.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.tracked_todo_tasks import (
    _LOCK_EXTEND_LUA,
    _LOCK_RELEASE_LUA,
    execute_tracked_todo,
)

pytestmark = pytest.mark.stress

MODULE = "app.workers.tasks.tracked_todo_tasks"
LOCK_KEY = "gaia_todo_exec:todo-1"
CLAIMANTS = 40


class _FakePool:
    """In-process ArqRedis stand-in: atomic SET-NX/EXISTS/Lua-release on a dict.

    ``set`` performs check-and-write with no awaits between them — the same
    atomicity the real single-threaded Redis gives the ``nx=True`` claim, so
    of N concurrent callers exactly one observes ``True``. ``eval`` mirrors
    the compare-and-delete release (and no-op renewal) scripts.
    """

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self.delete_calls: list[str] = []

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self._keys:
            return None
        self._keys[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        return int(self._keys.pop(key, None) is not None)

    async def exists(self, key: str) -> int:
        return int(key in self._keys)

    async def eval(self, lua: str, _numkeys: int, key: str, *args: str) -> int:
        token = args[0]
        if lua == _LOCK_EXTEND_LUA:
            return int(self._keys.get(key) == token)
        if lua == _LOCK_RELEASE_LUA:
            if self._keys.get(key) != token:
                return 0
            del self._keys[key]
            self.delete_calls.append(key)
            return 1
        raise ValueError(f"unexpected script: {lua}")


async def _yielding_execution(*_args: Any, **_kwargs: Any) -> str:
    """The winner's critical section: yields to the loop so concurrent
    claimants get scheduled while the lock is still held."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return "success:todo-1"


class TestTrackedTodoClaimRace:
    async def test_exactly_one_claim_wins_under_concurrent_race(self):
        pool = _FakePool()
        retry = AsyncMock(side_effect=_yielding_execution)
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}._execute_todo_with_retry", retry),
        ):
            # Bounded wait: if the lock ever breaks, a broken claim loop must
            # fail this test fast (10s) instead of hanging the worker until
            # pytest-timeout kills it.
            results = await asyncio.wait_for(
                asyncio.gather(*[execute_tracked_todo({}, "todo-1") for _ in range(CLAIMANTS)]),
                timeout=10,
            )

        assert results.count("success:todo-1") == 1
        assert results.count("skipped:todo-1 (lock held)") == CLAIMANTS - 1
        assert retry.await_count == 1
        assert pool.delete_calls == [LOCK_KEY]

    async def test_lock_holds_for_the_whole_critical_section_then_releases(self):
        """Adversarial: the winner holds the lock across loop turns; every claim
        arriving mid-section skips, and a claim after completion executes —
        proving the lock covers the section and is genuinely released."""
        pool = _FakePool()
        entered = asyncio.Event()
        release = asyncio.Event()
        retry = AsyncMock()

        async def held_execution(*_args: Any, **_kwargs: Any) -> str:
            entered.set()
            await release.wait()
            return "success:todo-1"

        retry.side_effect = held_execution
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}._execute_todo_with_retry", retry),
        ):
            winner = asyncio.create_task(execute_tracked_todo({}, "todo-1"))
            await entered.wait()

            mid_section = await asyncio.gather(
                *[execute_tracked_todo({}, "todo-1") for _ in range(10)]
            )

            assert mid_section == ["skipped:todo-1 (lock held)"] * 10
            assert retry.await_count == 1

            release.set()
            assert await winner == "success:todo-1"

            after_release = await execute_tracked_todo({}, "todo-1")
            assert after_release == "success:todo-1"
            assert retry.await_count == 2

        assert pool.delete_calls == [LOCK_KEY, LOCK_KEY]
