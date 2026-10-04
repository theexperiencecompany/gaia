"""Keep-warm for AGENT_LAB users: pause skip, sweep exemption, refresh scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.services.agent_lab.lab_runs import LAB_RUN_DIR_PREFIX, LAB_SEED_TIMEOUT_SECONDS
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
    """Minimal async context manager recording the acquired user."""

    def __init__(self, seen: list[str], user_id: str) -> None:
        self._seen = seen
        self._user_id = user_id

    async def __aenter__(self) -> MagicMock:
        self._seen.append(self._user_id)
        sbx = MagicMock()
        sbx.commands.run = AsyncMock()
        return sbx

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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(side_effect=_lab_only),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
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


def _lab_todo(
    updated_ago_hours: float, *, todo_id: str = "todo-lab", references: list[str] | None = None
) -> TodoDocument:
    now = datetime.now(UTC)
    return TodoDocument(
        id=todo_id,
        user_id="lab",
        title="Lab run",
        labels=[GAIA_TRACKED_LABEL],
        references=references if references is not None else ["run-1", "lab:run-1:cli-1"],
        created_at=now - timedelta(hours=updated_ago_hours + 1),
        updated_at=now - timedelta(hours=updated_ago_hours),
    )


class _FakePool:
    """Minimal stand-in for the ARQ redis pool (exists/set only)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True


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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_todos_without_references_do_not_cap(self) -> None:
        seen: list[str] = []
        plain = _lab_todo(48)
        plain.references = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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


class TestLabCapIgnoresNonLabReferences:
    async def test_old_unrelated_todo_does_not_block_the_cap(self) -> None:
        """The cap scan only counts routing entries; an old memory-link todo is invisible."""
        old_lab = _lab_todo(
            13, todo_id="old-lab", references=["run-old", "lab:run-old:cli-old"]
        )
        old_plain = _lab_todo(13, todo_id="old-plain", references=["some-memory-link"])

        def fake_acquire(user_id: str) -> _FakeAcquire:
            raise AssertionError("capped user must not be re-acquired")

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[old_lab, old_plain]),
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert result == "Refreshed 0 lab sandboxes, skipped 1 past cap"
        notify_create.assert_awaited_once()
        assert notify_create.await_args.args[0].metadata["todo_ids"] == ["old-lab"]

    async def test_only_unrelated_references_still_refreshes(self) -> None:
        """No routing entry anywhere means no lab run, however old the todo is."""
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(
                    return_value=[
                        _lab_todo(13, todo_id="old-plain", references=["some-memory-link"])
                    ]
                ),
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()

    async def test_bare_run_id_without_routing_entry_is_not_a_run(self) -> None:
        """A bare id alone (no lab: entry) never caps, even when stale."""
        seen: list[str] = []

        def fake_acquire(user_id: str) -> _FakeAcquire:
            return _FakeAcquire(seen, user_id)

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[_lab_todo(13, references=["run-1"])]),
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        notify_create.assert_not_awaited()


EVENTS_URL = "https://gaia.test/api/v1/lab/events"


class _SbxAcquire:
    """Yields a caller-owned fake sandbox."""

    def __init__(self, sbx: MagicMock) -> None:
        self._sbx = sbx

    async def __aenter__(self) -> MagicMock:
        return self._sbx

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class TestLabTokenReseed:
    async def test_refreshed_run_gets_a_fresh_token_staged(self) -> None:
        """Mint → canonical seed command → staged in the run workdir, per active run."""
        sbx = MagicMock()
        sbx.commands.run = AsyncMock()
        todo = _lab_todo(1, todo_id="t1", references=["run-abc", "lab:run-abc:cli-abc"])
        staged: list[tuple[str, str, str, str]] = []

        def fake_build(events_url: str, token: str, session_id: str, run_dir: str) -> str:
            staged.append((events_url, token, session_id, run_dir))
            return "SEED-CMD"

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[todo]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=lambda _: _SbxAcquire(sbx)),
            patch(f"{TASKS_MODULE}.lab_events_url", return_value=EVENTS_URL),
            patch(f"{TASKS_MODULE}.mint_lab_hooks_token", return_value="tok-fresh") as mint,
            patch(f"{TASKS_MODULE}.build_seed_command", side_effect=fake_build),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        mint.assert_called_once_with("lab", "run-abc")
        assert staged == [(EVENTS_URL, "tok-fresh", "run-abc", f"{LAB_RUN_DIR_PREFIX}/run-abc")]
        sbx.commands.run.assert_awaited_once_with("SEED-CMD", timeout=LAB_SEED_TIMEOUT_SECONDS)

    async def test_reseed_failure_does_not_fail_the_refresh(self) -> None:
        """One wedged seeder costs a warning line; the tick still counts the refresh."""
        sbx = MagicMock()
        sbx.commands.run = AsyncMock()
        todo = _lab_todo(1, todo_id="t1", references=["run-abc", "lab:run-abc:cli-abc"])

        with (
            patch(
                f"{TASKS_MODULE}.e2b_sandbox_repository.find_live_user_ids",
                AsyncMock(return_value=["lab"]),
            ),
            patch(
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
                AsyncMock(return_value=[todo]),
            ),
            patch(
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=lambda _: _SbxAcquire(sbx)),
            patch(f"{TASKS_MODULE}.lab_events_url", return_value=EVENTS_URL),
            patch(f"{TASKS_MODULE}.mint_lab_hooks_token", return_value="tok-fresh"),
            patch(
                f"{TASKS_MODULE}.build_seed_command",
                side_effect=RuntimeError("seed exploded"),
            ),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        sbx.commands.run.assert_not_awaited()


class TestLabMissPolicy:
    async def test_single_miss_takes_no_lab_action(self) -> None:
        """Until TODO-S1-supervisor-tick lands, one failed re-acquire only logs.

        No FAILED label, no tail delivery, no notification; other users still
        refresh. This locks the current no-action behavior as the spec.
        """
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
                f"{TASKS_MODULE}.todo_repository.list_active_tracked",
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
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes, skipped 0 past cap"
        add_labels.assert_not_awaited()
        notify_create.assert_not_awaited()
