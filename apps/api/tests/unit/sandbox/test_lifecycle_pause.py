"""Layer 3 — idle pause uses beta_pause (the original-bug regression).

The outage was `getattr(sbx, "pause")` → None → pause silently skipped. These
assert the lifecycle actually calls beta_pause and records the paused state, and
that the scheduler doesn't leak overlapping pause tasks.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool


def _paused_state_written(repo: AsyncMock) -> bool:
    # mark_paused is the only paused-state write, so any await records the pause.
    return repo.mark_paused.await_count > 0


async def test_pause_sandbox_calls_beta_pause_and_records_state() -> None:
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x")
    coll = AsyncMock()
    with patch.object(lifecycle, "e2b_sandbox_repository", coll):
        ok = await lifecycle._pause_sandbox("u1", entry)
    assert ok is True
    sbx.beta_pause.assert_awaited_once()
    assert _paused_state_written(coll), "must persist state=paused"


async def test_pause_sandbox_returns_false_and_swallows_errors() -> None:
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock(side_effect=RuntimeError("e2b 500"))
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x")
    with patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()):
        ok = await lifecycle._pause_sandbox("u1", entry)
    assert ok is False, "a pause failure must be reported, not raised"


async def test_scheduled_idle_pause_actually_pauses() -> None:
    # End-to-end of the scheduler→pause path with a zero idle window. Would fail
    # if beta_pause were never called (the original bug).
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    coll = AsyncMock()
    # No record: nothing on any replica has claimed this sandbox, so the pause
    # proceeds. The cross-replica guard is covered by its own tests below.
    coll.get_for_user = AsyncMock(return_value=None)
    with (
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
        patch.object(lifecycle, "e2b_sandbox_repository", coll),
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
        patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        await entry.pause_task
    sbx.beta_pause.assert_not_awaited()


async def test_scheduled_pause_aborts_if_another_replica_is_using_the_sandbox() -> None:
    """The sibling of the refcount check, for the replica that armed the timer.

    ``refcount`` is this process's own count, and the pause task outlives the
    acquisition lock that guarded the turn. So: replica A finishes a turn and
    arms the pause; the user replies and the LB sends it to replica B, which
    connects to the SAME sandbox (its id comes from Mongo) and starts a long
    run; A's timer then fires and pauses it underneath B. The user's tool call
    dies mid-command and its artifacts stop streaming.

    ``last_used_at`` in Mongo is the cross-replica proof of use — every release
    stamps it — so a recent stamp must abort the pause exactly like a local
    refcount would.
    """
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    coll = AsyncMock()
    # Another replica touched it one second ago — it is not idle.
    coll.get_for_user = AsyncMock(
        return_value=SimpleNamespace(last_used_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    with (
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 300),
        patch.object(lifecycle, "e2b_sandbox_repository", coll),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle.asyncio, "sleep", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        await entry.pause_task
    sbx.beta_pause.assert_not_awaited(), "paused a sandbox another replica was using"
    # The idleness check must read THIS user's cross-replica stamp.
    coll.get_for_user.assert_awaited_once_with("u1")


async def test_scheduled_pause_proceeds_when_no_replica_has_touched_it() -> None:
    """Control: a genuinely idle sandbox must still be paused (it is a cost saver)."""
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    coll = AsyncMock()
    coll.get_for_user = AsyncMock(
        return_value=SimpleNamespace(last_used_at=datetime.now(UTC) - timedelta(hours=1))
    )
    with (
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 300),
        patch.object(lifecycle, "e2b_sandbox_repository", coll),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle.asyncio, "sleep", AsyncMock()),
    ):
        lifecycle._schedule_pause("u1", entry)
        await entry.pause_task
    sbx.beta_pause.assert_awaited_once()


async def test_schedule_pause_cancels_a_prior_pending_task() -> None:
    # Two schedules without an intervening reuse must not leave two live tasks.
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    with (
        patch.object(
            lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 1000
        ),  # long: won't fire
        patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()),
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


async def test_idle_check_treats_the_window_edge_as_idle() -> None:
    # last_used_at exactly at the window boundary counts as idle (pause proceeds).
    # The strict `>` is what separates "used since the window" from "used exactly
    # at its edge"; a `>=` would wrongly keep an idle sandbox alive forever.
    now = datetime(2099, 1, 1, tzinfo=UTC)
    idle_since = now - timedelta(seconds=lifecycle.settings.E2B_SANDBOX_IDLE_PAUSE_SECONDS)
    coll = AsyncMock()
    coll.get_for_user = AsyncMock(return_value=SimpleNamespace(last_used_at=idle_since))
    with (
        patch.object(lifecycle, "_now", return_value=now),
        patch.object(lifecycle, "e2b_sandbox_repository", coll),
    ):
        assert await lifecycle._idle_on_every_replica("u1") is True
    coll.get_for_user.assert_awaited_once_with("u1")
