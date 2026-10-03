"""Keep-warm for AGENT_LAB users: pause skip, sweep exemption, refresh scope."""

from __future__ import annotations

import time
from types import TracebackType
from unittest.mock import AsyncMock, patch

import pytest

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
            patch.object(
                lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=True)
            ),
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
            patch.object(
                lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=False)
            ),
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

    async def __aenter__(self) -> None:
        self._seen.append(self._user_id)

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
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(side_effect=_lab_only),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes"

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
                f"{TASKS_MODULE}.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            ),
            patch(f"{TASKS_MODULE}.acquire_sandbox", side_effect=fake_acquire),
        ):
            result = await sandbox_tasks.refresh_lab_sandboxes({})
        assert seen == ["lab"]
        assert result == "Refreshed 1 lab sandboxes"


class TestLabBridge:
    async def test_bridge_mints_and_stages_for_flagged_user(self) -> None:
        sbx, _ = _make_entry()
        with (
            patch.object(
                lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=True)
            ),
            patch.object(
                lifecycle, "mint_sandbox_bridge_token", return_value=("tok", 900)
            ) as mint,
        ):
            token = await lifecycle._ensure_lab_bridge("lab", sbx)
        assert token == "tok"
        mint.assert_called_once_with("lab", "sbx-1")
        assert sbx.files.write.await_count == 2

    async def test_bridge_noop_for_unflagged_user(self) -> None:
        sbx, _ = _make_entry()
        with (
            patch.object(
                lifecycle, "is_agent_lab_enabled", AsyncMock(return_value=False)
            ),
            patch.object(
                lifecycle, "mint_sandbox_bridge_token", return_value=("tok", 900)
            ) as mint,
        ):
            assert await lifecycle._ensure_lab_bridge("plain", sbx) is None
        mint.assert_not_called()
        sbx.files.write.assert_not_awaited()


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
