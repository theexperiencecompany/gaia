"""Agent-lab sandbox upkeep: idle pause, the keep-warm tick, the run cap, saves and renewals.

A sandbox stays up only while a watched run is within the cap; every other
agent-lab sandbox pauses once idle. Boundaries mocked: e2b, Mongo repositories,
the flag, notifications; the tick, run-cap and pause logic run for real.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
import time
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services import feature_flags
from app.services.agent_lab import agents_home, lab_runs
from app.services.agent_lab.agents_saves import save_agents_home
from app.services.agent_lab.sandbox_events import SandboxEventKind
from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, refresh_sandbox_timeout
from app.workers.tasks import sandbox_tasks
from app.workers.tasks.sandbox_tasks import LabTickOutcome

pytestmark = pytest.mark.unit

TASKS_MODULE = "app.workers.tasks.sandbox_tasks"
LAB_TEMPLATE = "gaia-coder-8gb"


def _lab_only(user_id: str | None) -> bool:
    """Fake flag evaluation: only "lab" is flagged."""
    return user_id == "lab"


def _make_entry() -> tuple[AsyncMock, PooledSandbox]:
    sbx = AsyncMock()
    sbx.beta_pause = AsyncMock()
    sbx.files.write = AsyncMock()
    sbx.set_timeout = AsyncMock()
    sbx.sandbox_id = "sbx-1"
    return sbx, PooledSandbox(sandbox=sbx, last_canary_ts="x", refcount=0)


def _subscription(trigger_name: str, started_ago_hours: float, run_id: str) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name=trigger_name,
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
        trigger_data={"run_id": run_id},
        created_at=datetime.now(UTC) - timedelta(hours=started_ago_hours),
    )


def _lab_todo(
    started_ago_hours: float,
    *,
    todo_id: str = "todo-lab",
    run_ids: tuple[str, ...] = ("run-1",),
    other_watches: tuple[str, ...] = (),
) -> TodoDocument:
    """Build a todo whose run subscriptions started started_ago_hours ago; written to just now."""
    now = datetime.now(UTC)
    return TodoDocument(
        id=todo_id,
        user_id="lab",
        title="Lab run",
        labels=[GAIA_TRACKED_LABEL],
        trigger_subscriptions=[
            *(_subscription(name, started_ago_hours, "") for name in other_watches),
            *(
                _subscription(lab_runs.SANDBOX_RUN_TRIGGER, started_ago_hours, run_id)
                for run_id in run_ids
            ),
        ],
        created_at=now - timedelta(hours=started_ago_hours + 1),
        updated_at=now,
    )


class TestIdlePause:
    """The in-process idle pause skips only a sandbox a live run keeps awake."""

    async def _schedule(self, *, flagged: bool, todos: list[TodoDocument]) -> AsyncMock:
        sbx, entry = _make_entry()
        coll = AsyncMock()
        coll.get_for_user = AsyncMock(return_value=None)
        with (
            patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
            patch.object(lifecycle, "e2b_sandbox_repository", coll),
            patch.object(lifecycle, "_stop_watcher", AsyncMock()),
            patch.object(feature_flags.settings, "ENABLE_AGENT_LAB", flagged),
            patch(
                "app.db.repositories.todos.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=todos),
            ),
        ):
            lifecycle._schedule_pause("lab", entry)
            assert entry.pause_task is not None
            await entry.pause_task
        return sbx

    async def test_a_live_run_keeps_the_sandbox_from_pausing(self) -> None:
        sbx = await self._schedule(flagged=True, todos=[_lab_todo(1)])
        sbx.beta_pause.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_flagged_user_with_no_live_run_is_idle_paused(self) -> None:
        # Regression: every flagged user skipped the idle pause, so a sandbox
        # with nothing running billed until E2B's lifetime cap killed it.
        sbx = await self._schedule(flagged=True, todos=[])
        sbx.beta_pause.assert_awaited_once()

    async def test_a_run_past_the_cap_no_longer_keeps_it_awake(self) -> None:
        sbx = await self._schedule(flagged=True, todos=[_lab_todo(13)])
        sbx.beta_pause.assert_awaited_once()

    async def test_an_unflagged_user_is_idle_paused(self) -> None:
        sbx = await self._schedule(flagged=False, todos=[_lab_todo(1)])
        sbx.beta_pause.assert_awaited_once()


class TestSweepExemption:
    async def test_lab_users_exempt_from_evict(self) -> None:
        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_idle_user_ids",
                AsyncMock(return_value=["lab", "plain"]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(side_effect=_lab_only),
            ),
            patch(f"{TASKS_MODULE}.mark_sandbox_dead", AsyncMock()) as mark_dead,
        ):
            result = await sandbox_tasks.sweep_idle_sandboxes({})
        mark_dead.assert_awaited_once_with("plain")
        assert result.startswith("Evicted 1 idle sandboxes (cutoff=")


class TestRunCapStatus:
    def test_cap_counts_from_run_start_not_the_todos_last_write(self) -> None:
        """Every run event writes to the todo; a busy run must still hit the cap."""
        status = lab_runs.run_cap_status([_lab_todo(13)])
        assert status == lab_runs.RunCapStatus(live=False, capped_todo_ids=["todo-lab"])

    def test_other_watches_on_the_todo_are_not_runs(self) -> None:
        """An old email watch with no run beside it never counts as a run."""
        status = lab_runs.run_cap_status([_lab_todo(48, run_ids=(), other_watches=("gmail",))])
        assert status == lab_runs.RunCapStatus(live=False, capped_todo_ids=[])

    def test_one_fresh_run_keeps_the_user_live(self) -> None:
        status = lab_runs.run_cap_status(
            [_lab_todo(13, todo_id="old"), _lab_todo(1, todo_id="fresh")]
        )
        assert status.live
        assert status.capped_todo_ids == []


class _FakeAcquire:
    """Minimal async context manager recording the acquired user; its sandbox has minutes_left."""

    def __init__(self, seen: list[str], user_id: str, *, minutes_left: float = 50) -> None:
        self._seen = seen
        self._user_id = user_id
        self.sbx = MagicMock()
        self.sbx.commands.run = AsyncMock()
        self.sbx.get_info = AsyncMock(
            return_value=SimpleNamespace(end_at=datetime.now(UTC) + timedelta(minutes=minutes_left))
        )

    async def __aenter__(self) -> MagicMock:
        self._seen.append(self._user_id)
        return self.sbx

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class _FakePool:
    """Minimal stand-in for the ARQ redis pool (exists/set only)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True


class _Tick:
    """One keep-warm tick over fake boundaries, recording what it did."""

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.saved: list[str] = []
        self.pause = AsyncMock(return_value=True)
        self.renew = AsyncMock()
        self.report = AsyncMock()
        self.notify = AsyncMock()
        self.lookup = AsyncMock()
        self.pool = _FakePool()

    @contextmanager
    def world(
        self,
        todos_by_user: dict[str, list[TodoDocument]],
        *,
        flagged: set[str] | None = None,
        minutes_left: float = 50,
        broken: frozenset[str] = frozenset(),
    ) -> Iterator[None]:
        flagged_users = set(todos_by_user) if flagged is None else flagged
        self.lookup.return_value = list(todos_by_user)

        def acquire(user_id: str) -> _FakeAcquire:
            if user_id in broken:
                raise RuntimeError("e2b down")
            return _FakeAcquire(self.acquired, user_id, minutes_left=minutes_left)

        async def save(user_id: str, _sbx: object) -> bool:
            self.saved.append(user_id)
            return True

        async def todos(user_id: str, _trigger: str) -> list[TodoDocument]:
            return todos_by_user.get(user_id, [])

        async def is_flagged(user_id: str | None) -> bool:
            return user_id in flagged_users

        with ExitStack() as stack:
            for target, value in (
                ("settings.E2B_AGENT_LAB_TEMPLATE_ID", LAB_TEMPLATE),
                ("e2b_sandbox_repository.find_live_user_ids_on_template", self.lookup),
                ("todo_repository.find_active_by_user_and_trigger", todos),
                ("is_agent_lab_enabled", is_flagged),
                ("acquire_sandbox", acquire),
                ("save_agents_home", save),
                ("pause_idle_sandbox", self.pause),
                ("renew_sandbox", self.renew),
                ("report_sandbox_event", self.report),
                ("notification_service.create_notification", self.notify),
            ):
                stack.enter_context(patch(f"{TASKS_MODULE}.{target}", value))
            yield

    async def run(self) -> str:
        return await sandbox_tasks.refresh_lab_sandboxes({"redis": self.pool})


class TestKeepWarmTick:
    async def test_candidates_are_the_agent_lab_template_sandboxes(self) -> None:
        """Looked up by recorded template, so regular users cost no flag evaluation."""
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(1)]}):
            await tick.run()
        tick.lookup.assert_awaited_once_with(LAB_TEMPLATE)

    async def test_no_agent_lab_template_means_nothing_to_keep(self) -> None:
        with patch(f"{TASKS_MODULE}.settings.E2B_AGENT_LAB_TEMPLATE_ID", None):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert result == "Agent-lab template not configured; nothing to keep warm"

    async def test_a_live_run_is_kept_warm_and_saved_not_paused(self) -> None:
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(1)]}):
            result = await tick.run()
        assert (tick.acquired, tick.saved) == (["lab"], ["lab"])
        tick.pause.assert_not_awaited()
        assert result == "Kept 1 lab sandboxes warm, paused 0 idle, 0 failed"

    @pytest.mark.regression
    async def test_a_run_past_the_cap_gets_its_idle_sandbox_paused(self) -> None:
        # Regression: keep-warm stopped and left it to the idle pause, which
        # skipped lab users, so the sandbox ran until E2B killed it.
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(13)]}):
            result = await tick.run()
        assert tick.acquired == []
        tick.pause.assert_awaited_once_with("lab")
        assert result == "Kept 0 lab sandboxes warm, paused 1 idle, 0 failed"

    @pytest.mark.regression
    async def test_a_flagged_user_who_never_started_a_run_is_not_kept_warm(self) -> None:
        tick = _Tick()
        with tick.world({"lab": []}):
            await tick.run()
        assert tick.acquired == []
        tick.pause.assert_awaited_once_with("lab")

    async def test_a_revoked_flag_stops_keeping_a_live_run_warm(self) -> None:
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(1)]}, flagged=set()):
            await tick.run()
        assert tick.acquired == []
        tick.pause.assert_awaited_once_with("lab")

    async def test_the_cap_notice_goes_out_once_per_cap_window(self) -> None:
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(13)]}):
            await tick.run()
            await tick.run()
        tick.notify.assert_awaited_once()
        request = tick.notify.await_args.args[0]
        assert (request.user_id, request.type, request.source) == (
            "lab",
            NotificationType.WARNING,
            NotificationSourceEnum.BACKGROUND_JOB,
        )

    async def test_one_users_failure_does_not_stop_the_others(self) -> None:
        tick = _Tick()
        todos = {"bad": [_lab_todo(1)], "lab": [_lab_todo(1)]}
        with tick.world(todos, broken=frozenset({"bad"})):
            result = await tick.run()
        assert tick.acquired == ["lab"]
        assert result == "Kept 1 lab sandboxes warm, paused 0 idle, 1 failed"

    async def test_a_sandbox_near_its_cap_is_renewed_and_the_todos_hear_it(self) -> None:
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(1)]}, minutes_left=12):
            await tick.run()
        tick.renew.assert_awaited_once_with("lab")
        user_id, kind, _detail = tick.report.await_args.args
        assert (user_id, kind) == ("lab", SandboxEventKind.RENEWED)

    async def test_a_sandbox_far_from_its_cap_is_not_renewed(self) -> None:
        tick = _Tick()
        with tick.world({"lab": [_lab_todo(1)]}, minutes_left=50):
            await tick.run()
        tick.renew.assert_not_awaited()

    def test_the_summary_counts_every_outcome(self) -> None:
        assert {o.value for o in LabTickOutcome} == {"kept", "paused", "left", "failed"}


@pytest.mark.usefixtures("fake_redis")
class TestSaveAgentsHome:
    async def _save(self, run: AsyncMock) -> tuple[bool, AsyncMock]:
        sbx = MagicMock()
        sbx.commands.run = run
        report = AsyncMock()
        with patch("app.services.agent_lab.agents_saves.report_sandbox_event", report):
            ok = await save_agents_home("lab", sbx)
        return ok, report

    async def test_a_save_runs_gaia_save(self) -> None:
        run = AsyncMock()
        ok, report = await self._save(run)
        assert ok
        assert run.await_args.args[0] == agents_home.SAVE_SCRIPT
        report.assert_not_awaited()

    async def test_a_failed_save_wakes_the_todos_once_until_a_save_succeeds(self) -> None:
        failing = AsyncMock(side_effect=RuntimeError("tar: write failed"))
        _, first = await self._save(failing)
        _, second = await self._save(failing)
        _, after_success = await self._save(AsyncMock())
        _, third = await self._save(failing)
        assert [call.args[1] for call in first.await_args_list] == [SandboxEventKind.SAVE_FAILED]
        second.assert_not_awaited()
        after_success.assert_not_awaited()
        assert [call.args[1] for call in third.await_args_list] == [SandboxEventKind.SAVE_FAILED]


class TestRefreshTimeout:
    async def test_refreshes_when_window_elapsed(self) -> None:
        sbx, entry = _make_entry()
        entry.timeout_refreshed_at = 0.0
        assert await refresh_sandbox_timeout(entry) is True
        sbx.set_timeout.assert_awaited_once()
        assert entry.timeout_refreshed_at > 0.0

    async def test_skips_when_window_fresh(self) -> None:
        sbx, entry = _make_entry()
        entry.timeout_refreshed_at = time.monotonic()
        assert await refresh_sandbox_timeout(entry) is False
        sbx.set_timeout.assert_not_awaited()
