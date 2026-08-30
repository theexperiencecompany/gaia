"""Hermetic unit tests for ``DistributedLock``.

These exercise the real lock logic against a mock Redis client (no server), so
the mutation gate — which runs only hermetic tests — can see every branch, call
argument, and log message. Mutual exclusion and renewal against a *real* Redis
lease live in ``tests/integration/real/test_distributed_lock_real.py``; this file
is the line-by-line coverage.

``log.warning``/``log.error`` land in the wide event's ``warnings``/``errors``
arrays, so we assert their exact message and fields via ``captured_wide_event``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.constants.log_tags import LogTag
from app.utils import redis_lock
from app.utils.redis_lock import DistributedLock
from tests.helpers import captured_wide_event

TIMING = {
    "lease_seconds": 30,
    "acquire_timeout_seconds": 7,
    "renew_seconds": 3,
    "max_hold_seconds": 90,
}


def _mock_client(*, acquire: object) -> tuple[MagicMock, MagicMock]:
    """A redis client whose ``.lock(...)`` returns a lock with the given acquire.

    ``acquire`` is a bool the mock returns, or an exception it raises.
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


class _FakeLoop:
    """A loop stand-in whose ``time()`` returns a pre-scripted sequence."""

    def __init__(self, times: list[float]) -> None:
        self._times = times
        self._i = 0

    def time(self) -> float:
        value = self._times[self._i]
        self._i += 1
        return value


CONFIG_ERROR = (
    "max_hold_seconds must be >= lease_seconds; a cap below one lease "
    "would evict every holder before its first renewal"
)


@pytest.mark.unit
class TestConfigGuard:
    def test_max_hold_below_lease_raises_with_exact_message(self):
        with pytest.raises(ValueError) as exc:
            DistributedLock(
                "k",
                lease_seconds=30,
                acquire_timeout_seconds=1,
                renew_seconds=10,
                max_hold_seconds=29,
            )
        assert str(exc.value) == CONFIG_ERROR

    def test_max_hold_equal_to_lease_is_allowed(self):
        # A cap of exactly one lease is the boundary that must NOT raise — this is
        # what pins the `<` against a `<=` mutation.
        DistributedLock(
            "k",
            lease_seconds=30,
            acquire_timeout_seconds=1,
            renew_seconds=10,
            max_hold_seconds=30,
        )

    def test_max_hold_above_lease_is_allowed(self):
        DistributedLock(
            "k",
            lease_seconds=30,
            acquire_timeout_seconds=1,
            renew_seconds=10,
            max_hold_seconds=31,
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestHold:
    async def test_yields_false_and_warns_when_redis_unconfigured(self):
        with patch.object(redis_lock.redis_cache, "redis", None):
            async with captured_wide_event() as event:
                async with DistributedLock("k", **TIMING).hold() as held:
                    assert held is False
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.LOCK} Redis not configured; lease not taken"
        assert warning["lock_key"] == "k"

    async def test_acquires_with_exact_lock_parameters(self):
        client, lock = _mock_client(acquire=True)
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with DistributedLock("k", **TIMING).hold() as held:
                assert held is True
        client.lock.assert_called_once_with("k", timeout=30, blocking_timeout=7, thread_local=False)
        lock.acquire.assert_awaited_once()
        lock.release.assert_awaited_once()

    async def test_yields_false_and_warns_on_acquire_timeout(self):
        client, lock = _mock_client(acquire=False)
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with captured_wide_event() as event:
                async with DistributedLock("k", **TIMING).hold() as held:
                    assert held is False
        # Never acquired → must not release (would free another holder's lease).
        lock.release.assert_not_called()
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.LOCK} Timed out acquiring lease"
        assert warning["lock_key"] == "k"
        assert warning["acquire_timeout_seconds"] == 7

    async def test_yields_false_and_warns_on_acquire_redis_error(self):
        client, lock = _mock_client(acquire=RedisConnectionError("down"))
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with captured_wide_event() as event:
                async with DistributedLock("k", **TIMING).hold() as held:
                    assert held is False
        lock.release.assert_not_called()
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.LOCK} Redis error acquiring lease; lease not taken"
        assert warning["lock_key"] == "k"
        assert warning["error"] == "down"
        assert warning["error_type"] == "ConnectionError"

    async def test_watchdog_renews_the_real_held_lease(self):
        # renew_seconds=0 lets the watchdog reach its first extend the moment we
        # yield to the loop, proving hold() hands the REAL lock to the watchdog —
        # passing None instead would AttributeError inside it and surface on exit.
        client, lock = _mock_client(acquire=True)
        dl = DistributedLock(
            "k", lease_seconds=5, acquire_timeout_seconds=1, renew_seconds=0, max_hold_seconds=1000
        )
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with dl.hold() as held:
                assert held is True
                for _ in range(5):
                    await asyncio.sleep(0)
        assert lock.extend.await_count >= 1
        lock.extend.assert_awaited_with(5, replace_ttl=True)

    async def test_release_failure_is_logged_not_raised(self):
        client, lock = _mock_client(acquire=True)
        lock.release = AsyncMock(side_effect=RedisConnectionError("lease gone"))
        with patch.object(redis_lock.redis_cache, "redis", client):
            async with captured_wide_event() as event:
                async with DistributedLock("k", **TIMING).hold() as held:
                    assert held is True
        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.LOCK} Lease lost before release"
        assert error["lock_key"] == "k"
        assert error["error"] == "lease gone"
        assert error["error_type"] == "ConnectionError"


@pytest.mark.unit
@pytest.mark.asyncio
class TestRenewUntilCap:
    async def _run(
        self, lock_obj: DistributedLock, mock_lock: MagicMock, times: list[float]
    ) -> dict[str, Any]:
        async with captured_wide_event() as event:
            with (
                patch("app.utils.redis_lock.asyncio.sleep", new=AsyncMock()) as sleep_mock,
                patch(
                    "app.utils.redis_lock.asyncio.get_running_loop",
                    return_value=_FakeLoop(times),
                ),
            ):
                await lock_obj._renew_until_cap(mock_lock)
        self._sleep_mock = sleep_mock
        return event

    async def test_renews_then_caps_at_max_hold(self):
        lock_obj = DistributedLock(
            "k", lease_seconds=5, acquire_timeout_seconds=1, renew_seconds=2, max_hold_seconds=10
        )
        mock_lock = MagicMock()
        mock_lock.extend = AsyncMock()
        # deadline base 0 -> deadline 10; extend at t=1 and t=2; cap at t=10 (== deadline).
        event = await self._run(lock_obj, mock_lock, times=[0, 1, 2, 10])

        assert mock_lock.extend.await_count == 2
        mock_lock.extend.assert_awaited_with(5, replace_ttl=True)
        self._sleep_mock.assert_awaited_with(2)
        (error,) = event["errors"]
        assert (
            error["msg"]
            == f"{LogTag.LOCK} Max hold exceeded; stopping renewal so the lease expires"
        )
        assert error["lock_key"] == "k"
        assert error["max_hold_seconds"] == 10

    async def test_stops_and_logs_when_extend_fails(self):
        lock_obj = DistributedLock(
            "k", lease_seconds=5, acquire_timeout_seconds=1, renew_seconds=2, max_hold_seconds=100
        )
        mock_lock = MagicMock()
        mock_lock.extend = AsyncMock(side_effect=RedisConnectionError("lease gone"))
        # Under the cap the whole time, so only the extend failure can end the loop.
        event = await self._run(lock_obj, mock_lock, times=[0, 1, 2])

        mock_lock.extend.assert_awaited_once_with(5, replace_ttl=True)
        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.LOCK} Lost lease while holding it"
        assert error["lock_key"] == "k"
        assert error["error"] == "lease gone"
        assert error["error_type"] == "ConnectionError"


@pytest.mark.unit
@pytest.mark.asyncio
class TestRunIdempotent:
    async def test_runs_work_under_the_lease_when_held(self):
        client, lock = _mock_client(acquire=True)
        ran: list[int] = []
        with patch.object(redis_lock.redis_cache, "redis", client):
            await DistributedLock("k", **TIMING).run_idempotent(lambda: _append(ran))
        assert ran == [1]
        lock.release.assert_awaited_once()

    async def test_runs_work_and_warns_when_not_held(self):
        ran: list[int] = []
        with patch.object(redis_lock.redis_cache, "redis", None):
            async with captured_wide_event() as event:
                await DistributedLock("k", **TIMING).run_idempotent(lambda: _append(ran))
        assert ran == [1]
        # The "not held" branch emits this warning (hold() also warns that Redis is
        # unconfigured); a run that skipped the branch would leave it absent.
        not_held = [w for w in event["warnings"] if "Lease not held" in w["msg"]]
        assert len(not_held) == 1
        assert (
            not_held[0]["msg"]
            == f"{LogTag.LOCK} Lease not held; running work unsynchronized (idempotent)"
        )
        assert not_held[0]["lock_key"] == "k"

    async def test_work_error_is_not_swallowed(self):
        async def boom() -> None:
            raise ValueError("boom")

        with patch.object(redis_lock.redis_cache, "redis", None):
            with pytest.raises(ValueError, match="boom"):
                await DistributedLock("k", **TIMING).run_idempotent(boom)


async def _append(target: list[int]) -> None:
    target.append(1)
