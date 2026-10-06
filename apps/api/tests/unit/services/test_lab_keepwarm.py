"""Keep-warm for AGENT_LAB users: pause skip, sweep exemption, refresh scope."""

from __future__ import annotations

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
from app.services.agent_lab import agents_home, lab_runs
from app.services.agent_lab.sandbox_events import SandboxEventKind
from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, refresh_sandbox_timeout
from app.workers.tasks import sandbox_tasks

pytestmark = pytest.mark.unit

TASKS_MODULE = "app.workers.tasks.sandbox_tasks"


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


class TestPauseSkip:
    async def test_pause_skipped_for_flagged_user(self) -> None:
        sbx, entry = _make_entry()
        coll = AsyncMock()
        coll.get_for_user = AsyncMock(return_value=None)
        with (
            patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
            patch.object(lifecycle, "e2b_sandbox_repository", coll),
            patch.object(lifecycle, "_stop_watcher", AsyncMock()),
            patch.object(lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=True)),
        ):
            lifecycle._schedule_pause("lab", entry)
            assert entry.pause_task is not None
            await entry.pause_task
        sbx.beta_pause.assert_not_awaited()
        coll.mark_paused.assert_not_awaited()

    async def test_pause_proceeds_for_unflagged_user(self) -> None:
        sbx, entry = _make_entry()
        coll = AsyncMock()
        coll.get_for_user = AsyncMock(return_value=None)
        with (
            patch.object(lifecycle.settings, "E2B_SANDBOX_IDLE_PAUSE_SECONDS", 0),
            patch.object(lifecycle, "e2b_sandbox_repository", coll),
            patch.object(lifecycle, "_stop_watcher", AsyncMock()),
            patch.object(lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=False)),
        ):
            lifecycle._schedule_pause("plain", entry)
            assert entry.pause_task is not None
            await entry.pause_task
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


class _FakeAcquire:
    """Minimal async context manager recording the acquired user; its sandbox has minutes_left."""

    def __init__(
        self,
        seen: list[str],
        user_id: str,
        *,
        minutes_left: float = 50,
        run: AsyncMock | None = None,
    ) -> None:
        self._seen = seen
        self._user_id = user_id
        self.sbx = MagicMock()
        self.sbx.commands.run = run or AsyncMock()
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


class TestRefreshScope:
    async def test_refresh_touches_only_lab_users(self) -> None:
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab", "plain"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(side_effect=_lab_only),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"

    async def test_refresh_failure_does_not_abort_others(self) -> None:
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            if user_id == "bad":
                raise RuntimeError("e2b down")
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["bad", "lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"


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


class _FakePool:
    """Minimal stand-in for the ARQ redis pool (exists/set/delete only)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class TestLabRunCap:
    async def test_cap_hit_skips_refresh_and_notifies(self) -> None:
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[_lab_todo(13)]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == []
        assert result == "Refreshed 0 lab sandboxes, skipped 1 past cap"
        notify_create.assert_awaited_once()
        request = notify_create.await_args.args[0]
        assert request.user_id == "lab"
        assert request.type == NotificationType.WARNING
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB

    async def test_fresh_run_still_refreshes(self) -> None:
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[_lab_todo(1)]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_todos_without_run_subscriptions_do_not_cap(self) -> None:
        seen: list[str] = []
        plain = _lab_todo(48, run_ids=())

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[plain]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_one_fresh_run_keeps_refreshing(self) -> None:
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[_lab_todo(13, todo_id="old"), _lab_todo(1, todo_id="new")]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_cap_notify_deduped_by_redis_cooldown(self) -> None:
        pool = _FakePool()

        def fake_acquire(user_id: str) -> _FakeAcquire:
            raise AssertionError("capped user must not be re-acquired")

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[_lab_todo(13)]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            first = await sandbox_tasks.refresh_lab_sandboxes({"redis": pool})
            second = await sandbox_tasks.refresh_lab_sandboxes({"redis": pool})
        assert first == "Refreshed 0 lab sandboxes, skipped 1 past cap"
        assert second == "Refreshed 0 lab sandboxes, skipped 1 past cap"
        notify_create.assert_awaited_once()


class TestLabCapCountsRunsOnly:
    async def test_cap_counts_from_run_start_not_the_todos_last_write(self) -> None:
        """Every run event writes to the todo; a busy run must still hit the cap."""
        busy = _lab_todo(13)
        assert busy.updated_at is not None
        assert (datetime.now(UTC) - busy.updated_at).total_seconds() < 60

        def fake_acquire(user_id: str) -> _FakeAcquire:
            raise AssertionError("capped user must not be re-acquired")

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[busy]),
            ),
            patch(f"{TASKS_MODULE}.is_agent_lab_enabled", AsyncMock(return_value=True)),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(f"{TASKS_MODULE}.notification_service.create_notification", AsyncMock()),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert result == "Refreshed 0 lab sandboxes, skipped 1 past cap"

    async def test_other_watches_on_the_todo_are_not_runs(self) -> None:
        """An old email watch beside a fresh run never caps; only run subscriptions count."""
        seen: list[str] = []
        todo = _lab_todo(1, other_watches=("gmail_new_message",))
        todo.trigger_subscriptions[0] = _subscription("gmail_new_message", 48, "")

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[todo]),
            ),
            patch(f"{TASKS_MODULE}.is_agent_lab_enabled", AsyncMock(return_value=True)),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification", AsyncMock()
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_candidates_are_looked_up_by_the_run_trigger(self) -> None:
        lookup = AsyncMock(return_value=[])
        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger", lookup),
            patch(f"{TASKS_MODULE}.is_agent_lab_enabled", AsyncMock(return_value=True)),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=lambda u: _FakeAcquire([], u)),
        ):
            await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        lookup.assert_awaited_once_with("lab", lab_runs.SANDBOX_RUN_TRIGGER)


class TestLabMissPolicy:
    async def test_single_miss_takes_no_lab_action(self) -> None:
        """A failed re-acquire only logs: a dead run is its todo's concern, not keep-warm's."""
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            if user_id == "flaky":
                raise RuntimeError("e2b down")
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["flaky", "lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.find_active_by_user_and_trigger",
                AsyncMock(return_value=[_lab_todo(1)]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
            patch(f"{TASKS_MODULE}.todo_repository.add_labels", AsyncMock()) as add_labels,
            patch(
                f"{TASKS_MODULE}.notification_service.create_notification",
                AsyncMock(),
            ) as notify_create,
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({"redis": _FakePool()})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        add_labels.assert_not_awaited()
        notify_create.assert_not_awaited()


class TestKeepWarmSavesAndRenews:
    """Each tick saves the agents' home; only a sandbox near E2B's hour gets a pause+resume."""

    async def _tick(
        self, acquire: _FakeAcquire, pool: _FakePool | None = None
    ) -> tuple[AsyncMock, AsyncMock]:
        renew = AsyncMock()
        report = AsyncMock()
        with (
            patch(f"{TASKS_MODULE}.acquire_sandbox", return_value=acquire),
            patch(f"{TASKS_MODULE}.renew_sandbox", renew),
            patch(f"{TASKS_MODULE}.report_sandbox_event", report),
        ):
            await sandbox_tasks._keep_lab_sandbox({"redis": pool or _FakePool()}, "lab")
        return renew, report

    async def test_every_tick_saves_the_agents_home(self) -> None:
        acquire = _FakeAcquire([], "lab", minutes_left=50)
        renew, report = await self._tick(acquire)
        assert acquire.sbx.commands.run.await_args.args[0] == agents_home.SAVE_SCRIPT
        renew.assert_not_awaited()
        report.assert_not_awaited()

    async def test_a_sandbox_near_its_hour_is_renewed_and_the_todos_hear_it(self) -> None:
        acquire = _FakeAcquire([], "lab", minutes_left=12)
        renew, report = await self._tick(acquire)
        renew.assert_awaited_once_with("lab")
        user_id, kind, _detail = report.await_args.args
        assert (user_id, kind) == ("lab", SandboxEventKind.RENEWED)

    async def test_a_failed_save_wakes_the_todos_once_until_a_save_succeeds(self) -> None:
        pool = _FakePool()
        failing = AsyncMock(side_effect=RuntimeError("tar: write failed"))
        _, first = await self._tick(_FakeAcquire([], "lab", run=failing), pool)
        _, second = await self._tick(_FakeAcquire([], "lab", run=failing), pool)
        _, after_success = await self._tick(_FakeAcquire([], "lab"), pool)
        _, third = await self._tick(_FakeAcquire([], "lab", run=failing), pool)
        assert [call.args[1] for call in first.await_args_list] == [SandboxEventKind.SAVE_FAILED]
        second.assert_not_awaited()
        after_success.assert_not_awaited()
        assert [call.args[1] for call in third.await_args_list] == [SandboxEventKind.SAVE_FAILED]
