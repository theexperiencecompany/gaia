"""Layer 3 — acquire_sandbox central death-eviction (#3).

Mocks the AsyncSandbox boundary (is_running, kill) and patches _acquire_or_create
+ the mongo collection. Asserts on REAL pool state (is the dead entry gone?) and
the real mongo side effect (state=dead) — not mock.called. mark_sandbox_dead runs
for real so we exercise the actual eviction path all four tools depend on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
import uuid

from e2b import NotFoundException, TimeoutException
import pytest

from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _run(
    sandbox: AsyncMock, *, body_error: Exception | None
) -> AsyncIterator[tuple[str, Any, AsyncMock, Any, Exception | None]]:
    """Drive acquire_sandbox for a fresh user; yield (user_id, pool, coll, sched)."""
    user_id = f"u-{uuid.uuid4().hex}"
    pool = get_sandbox_pool()
    entry = PooledSandbox(sandbox=sandbox, last_canary_ts="x")

    async def fake_acquire_or_create(uid: str) -> PooledSandbox:
        pool.put(uid, entry)  # mirror real behavior: entry lives in the pool
        return entry

    coll = AsyncMock()
    with (
        patch.object(lifecycle, "_acquire_or_create", side_effect=fake_acquire_or_create),
        patch.object(lifecycle, "e2b_sandboxes_collection", coll),
        patch.object(lifecycle, "_schedule_pause") as sched,
    ):
        raised: Exception | None = None
        try:
            async with lifecycle.acquire_sandbox(user_id) as sbx:
                assert sbx is sandbox
                if body_error is not None:
                    raise body_error
        except Exception as e:  # noqa: BLE001
            raised = e
        yield user_id, pool, coll, sched, raised
    pool.evict(user_id)  # cleanup any survivor


def _dead_state_written(coll: AsyncMock) -> bool:
    for call in coll.update_one.call_args_list:
        update = call.args[1] if len(call.args) > 1 else call.kwargs.get("update", {})
        if update.get("$set", {}).get("state") == "dead":
            return True
    return False


async def test_dead_sandbox_is_evicted_when_tool_op_fails() -> None:
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(return_value=False)  # /health says dead
    async with _run(sbx, body_error=RuntimeError("tool blew up")) as (
        uid,
        pool,
        coll,
        sched,
        raised,
    ):
        assert isinstance(raised, RuntimeError), "original exception must propagate"
        assert pool.get(uid) is None, "a dead sandbox must be evicted from the pool"
        assert _dead_state_written(coll), "mongo must be marked state=dead"
        sched.assert_not_called()  # do not schedule a pause on a dead sandbox


async def test_live_sandbox_is_kept_when_command_errors() -> None:
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(return_value=True)  # /health says alive
    async with _run(sbx, body_error=RuntimeError("grep: no match")) as (
        uid,
        pool,
        coll,
        sched,
        raised,
    ):
        assert isinstance(raised, RuntimeError)
        assert pool.get(uid) is not None, "a live sandbox must NOT be evicted on a command error"
        assert not _dead_state_written(coll)


async def test_file_not_found_on_a_live_sandbox_does_not_evict() -> None:
    # A read/edit of a MISSING FILE raises NotFoundException, but the sandbox is
    # alive. Eviction keys off is_running() (not the exception TYPE) precisely so
    # a file-404 doesn't get mistaken for a dead sandbox — catching
    # NotFoundException by type (as the naive approach would) would evict a
    # healthy sandbox on every read of a non-existent path.
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(return_value=True)  # sandbox is fine; only the file is missing
    async with _run(sbx, body_error=NotFoundException("file /workspace/x not found")) as (
        uid,
        pool,
        coll,
        sched,
        raised,
    ):
        assert isinstance(raised, NotFoundException)
        assert pool.get(uid) is not None, "a missing FILE must not evict a healthy sandbox"
        assert not _dead_state_written(coll)


async def test_command_deadline_timeout_does_not_evict_a_live_sandbox() -> None:
    # A slow command hits its deadline → TimeoutException, but the SANDBOX is
    # fine. Eviction keys off is_running(), so a slow command must not evict a
    # healthy (just busy) sandbox — only a wedged/dead one.
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(return_value=True)  # alive, the command was just slow
    async with _run(
        sbx, body_error=TimeoutException("exceeding 'timeout' — long running request")
    ) as (uid, pool, coll, sched, raised):
        assert isinstance(raised, TimeoutException)
        assert pool.get(uid) is not None, "a slow command must not evict a healthy sandbox"
        assert not _dead_state_written(coll)


async def test_eviction_when_health_probe_itself_raises() -> None:
    # is_running raising (transport gone) must be treated as dead, not crash.
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(side_effect=ConnectionError("gone"))
    async with _run(sbx, body_error=RuntimeError("op failed")) as (
        uid,
        pool,
        coll,
        sched,
        raised,
    ):
        assert isinstance(raised, RuntimeError)
        assert pool.get(uid) is None, "unreachable /health → treat as dead → evict"


async def test_happy_path_keeps_sandbox_and_schedules_pause() -> None:
    sbx = AsyncMock()
    sbx.is_running = AsyncMock(return_value=True)
    async with _run(sbx, body_error=None) as (uid, pool, coll, sched, raised):
        assert raised is None
        assert pool.get(uid) is not None
        sched.assert_called_once()  # last in-flight call schedules the idle pause
        sbx.is_running.assert_not_called()  # no health probe on success — happy path is cheap
        assert not _dead_state_written(coll)
