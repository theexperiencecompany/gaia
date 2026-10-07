"""Layer 3 — idle pause uses beta_pause (the original-bug regression).

The outage was getattr(sbx, "pause") → None → pause silently skipped. These
assert the lifecycle actually calls beta_pause and records the paused state, and
that the scheduler doesn't leak overlapping pause tasks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.sandbox_models import E2bSandboxDocument, E2bSandboxState
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services import feature_flags
from app.services.agent_lab import lab_runs
from app.services.sandbox import lifecycle, pool as pool_module
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


LAB_TEMPLATE = "gaia-coder-8gb"


def _record(*, used_ago_s: int = 3600, template_id: str | None = None) -> E2bSandboxDocument:
    """Build a running sandbox record last used used_ago_s seconds ago, on any replica."""
    return E2bSandboxDocument(
        user_id="u1",
        shard_id=0,
        state=E2bSandboxState.ACTIVE,
        sandbox_id="sbx-1",
        template_id=template_id,
        last_used_at=datetime.now(UTC) - timedelta(seconds=used_ago_s),
    )


@contextmanager
def _idle_timer_world(
    entry: PooledSandbox,
    record: E2bSandboxDocument | None,
    *,
    todos: list[TodoDocument] | None = None,
) -> Iterator[tuple[str, AsyncMock]]:
    """Pool the entry under a fresh user with a zero idle window; yields (user_id, repo)."""
    user_id = f"u-{uuid.uuid4().hex}"
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=record)
    get_sandbox_pool().put(user_id, entry)
    try:
        with (
            patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
            patch.object(pool_module.settings, "E2B_AGENT_LAB_TEMPLATE_ID", LAB_TEMPLATE),
            patch.object(lifecycle, "e2b_sandbox_repository", repo),
            patch.object(lifecycle, "_stop_watcher", AsyncMock()),
            patch.object(lifecycle, "save_agents_home", AsyncMock(return_value=True)),
            patch(
                "app.db.repositories.todos.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=todos or []),
            ),
        ):
            yield user_id, repo
    finally:
        get_sandbox_pool().evict(user_id)


async def _fire_idle_timer(entry: PooledSandbox, user_id: str) -> None:
    lifecycle._schedule_pause(user_id, entry)
    assert entry.pause_task is not None
    await entry.pause_task


def _run_todo(started_ago_hours: float) -> TodoDocument:
    return TodoDocument(
        id="todo-lab",
        user_id="u1",
        title="Lab run",
        labels=[GAIA_TRACKED_LABEL],
        trigger_subscriptions=[
            TriggerSubscription(
                trigger_name=lab_runs.SANDBOX_RUN_TRIGGER,
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
                trigger_data={lab_runs.RUN_ID_KEY: "run-1"},
                created_at=datetime.now(UTC) - timedelta(hours=started_ago_hours),
            )
        ],
    )


async def test_scheduled_idle_pause_actually_pauses() -> None:
    # End-to-end of the scheduler→pause path with a zero idle window. Would fail
    # if beta_pause were never called (the original bug).
    sbx = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    with _idle_timer_world(entry, _record()) as (user_id, repo):
        await _fire_idle_timer(entry, user_id)
        assert get_sandbox_pool().get(user_id) is None, "a frozen sandbox stayed pooled"
    sbx.beta_pause.assert_awaited_once()
    assert _paused_state_written(repo)


@pytest.mark.regression
async def test_the_idle_timer_pauses_under_the_users_lock() -> None:
    # Regression: the timer paused without the lock, so a command another
    # replica started inside the (up to 120s) save was frozen mid-run.
    sbx = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    held: list[str] = []
    paused_holding: list[bool] = []

    @asynccontextmanager
    async def lock(user_id: str) -> AsyncIterator[None]:
        held.append(user_id)
        try:
            yield
        finally:
            held.remove(user_id)

    async def pause() -> None:
        paused_holding.append(bool(held))

    sbx.beta_pause = AsyncMock(side_effect=pause)
    with (
        _idle_timer_world(entry, _record()) as (user_id, _repo),
        patch.object(get_sandbox_pool(), "distributed_lock", lock),
    ):
        await _fire_idle_timer(entry, user_id)
    assert paused_holding == [True]


async def test_scheduled_pause_aborts_if_work_arrived() -> None:
    # refcount > 0 when the timer fires → must NOT pause.
    sbx = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=1)
    with _idle_timer_world(entry, _record()) as (user_id, _repo):
        await _fire_idle_timer(entry, user_id)
    sbx.beta_pause.assert_not_awaited()


async def test_scheduled_pause_aborts_if_another_replica_is_using_the_sandbox() -> None:
    """A recent last_used_at from another replica aborts the pause even at zero local refcount."""
    sbx = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    with (
        _idle_timer_world(entry, _record(used_ago_s=1)) as (user_id, repo),
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 300),
        patch.object(lifecycle.asyncio, "sleep", AsyncMock()),
    ):
        await _fire_idle_timer(entry, user_id)
    sbx.beta_pause.assert_not_awaited(), "paused a sandbox another replica was using"
    repo.get_for_user.assert_awaited_with(user_id)


async def test_scheduled_pause_proceeds_when_no_replica_has_touched_it() -> None:
    """Control: a genuinely idle sandbox must still be paused (it is a cost saver)."""
    sbx = AsyncMock()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)
    with (
        _idle_timer_world(entry, _record(used_ago_s=3600)) as (user_id, _repo),
        patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 300),
        patch.object(lifecycle.asyncio, "sleep", AsyncMock()),
    ):
        await _fire_idle_timer(entry, user_id)
    sbx.beta_pause.assert_awaited_once()


class TestLabIdlePause:
    """An agent-lab sandbox skips the idle pause only while a watched run is within the cap."""

    async def _fire(self, todos: list[TodoDocument], *, flag_on: bool = True) -> AsyncMock:
        sbx = AsyncMock()
        entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", template_id=LAB_TEMPLATE)
        with (
            _idle_timer_world(entry, _record(template_id=LAB_TEMPLATE), todos=todos) as (
                user_id,
                _repo,
            ),
            patch.object(feature_flags.settings, "ENABLE_AGENT_LAB", flag_on),
        ):
            await _fire_idle_timer(entry, user_id)
        return sbx

    async def test_a_live_run_keeps_the_sandbox_from_pausing(self) -> None:
        sbx = await self._fire([_run_todo(1)])
        sbx.beta_pause.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_live_run_stays_up_when_the_flag_reads_off(self) -> None:
        # Regression: the flag reads off whenever PostHog is unreachable, and
        # that paused sandboxes with a coding agent working inside.
        sbx = await self._fire([_run_todo(1)], flag_on=False)
        sbx.beta_pause.assert_not_awaited()

    @pytest.mark.regression
    async def test_no_live_run_means_it_is_idle_paused(self) -> None:
        # Regression: every flagged user skipped the idle pause, so a sandbox
        # with nothing running billed until E2B's lifetime cap killed it.
        sbx = await self._fire([])
        sbx.beta_pause.assert_awaited_once()

    async def test_a_run_past_the_cap_no_longer_keeps_it_awake(self) -> None:
        sbx = await self._fire([_run_todo(13)])
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
