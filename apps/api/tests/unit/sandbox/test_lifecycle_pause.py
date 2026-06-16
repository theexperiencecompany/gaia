"""Layer 3 — idle pause uses beta_pause (the original-bug regression).

The outage was `getattr(sbx, "pause")` → None → pause silently skipped. These
assert the lifecycle actually calls beta_pause and records the paused state, and
that the scheduler doesn't leak overlapping pause tasks.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool

pytestmark = pytest.mark.unit


def _paused_state_written(coll: AsyncMock) -> bool:
    for call in coll.update_one.call_args_list:
        update = call.args[1] if len(call.args) > 1 else call.kwargs.get("update", {})
        if update.get("$set", {}).get("state") == "paused":
            return True
    return False


async def test_pause_sandbox_calls_beta_pause_and_records_state() -> None:
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x")
    coll = AsyncMock()
    with patch.object(lifecycle, "e2b_sandboxes_collection", coll):
        ok = await lifecycle._pause_sandbox("u1", entry)
    assert ok is True
    sbx.beta_pause.assert_awaited_once()
    assert _paused_state_written(coll), "must persist state=paused"


async def test_pause_sandbox_returns_false_and_swallows_errors() -> None:
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock(side_effect=RuntimeError("e2b 500"))
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x")
    with patch.object(lifecycle, "e2b_sandboxes_collection", AsyncMock()):
        ok = await lifecycle._pause_sandbox("u1", entry)
    assert ok is False, "a pause failure must be reported, not raised"


async def test_scheduled_idle_pause_actually_pauses() -> None:
    # End-to-end of the scheduler→pause path with a zero idle window. Would fail
    # if beta_pause were never called (the original bug).
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    coll = AsyncMock()
    with (
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
        patch.object(lifecycle, "e2b_sandboxes_collection", coll),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        await entry.pause_task  # let the debounced task run to completion
    sbx.beta_pause.assert_awaited_once()
    assert _paused_state_written(coll)


async def test_scheduled_pause_aborts_if_work_arrived() -> None:
    # refcount > 0 when the timer fires → must NOT pause.
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=1)
    with (
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
        patch.object(lifecycle, "e2b_sandboxes_collection", AsyncMock()),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        await entry.pause_task
    sbx.beta_pause.assert_not_awaited()


async def test_schedule_pause_cancels_a_prior_pending_task() -> None:
    # Two schedules without an intervening reuse must not leave two live tasks.
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    with (
        patch.object(
            lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 1000
        ),  # long: won't fire
        patch.object(lifecycle, "e2b_sandboxes_collection", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        first = entry.pause_task
        lifecycle._schedule_pause("u1", entry)
        second = entry.pause_task
        await asyncio.sleep(0)  # let the cancellation propagate
        assert first is not second
        assert first.cancelled(), "the prior pause task must be cancelled"
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second


async def test_pause_sandbox_for_user_noop_when_not_pooled() -> None:
    missing = f"u-{uuid.uuid4().hex}"
    get_sandbox_pool().evict(missing)
    assert await lifecycle.pause_sandbox_for_user(missing) is False
