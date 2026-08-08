"""Unit tests for app.workers.tasks.sandbox_tasks.

``sweep_idle_sandboxes`` marks sandboxes idle past the eviction window as dead
so the next request gets a fresh one. Per-user failures are logged and must
never abort the rest of the sweep.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.workers.tasks.sandbox_tasks import sweep_idle_sandboxes

MODULE = "app.workers.tasks.sandbox_tasks"


class TestSweepIdleSandboxes:
    async def test_no_idle_users_evicts_nothing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "E2B_SANDBOX_EVICT_DAYS", 1)
        with (
            patch(
                f"{MODULE}.e2b_sandbox_repository.find_idle_user_ids",
                AsyncMock(return_value=[]),
            ),
            patch(f"{MODULE}.mark_sandbox_dead", AsyncMock()) as mark_dead,
        ):
            result = await sweep_idle_sandboxes({})

        assert result.startswith("Evicted 0 idle sandboxes (cutoff=")
        mark_dead.assert_not_awaited()

    async def test_evicts_every_idle_user(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "E2B_SANDBOX_EVICT_DAYS", 1)
        before = datetime.now(UTC)
        with (
            patch(
                f"{MODULE}.e2b_sandbox_repository.find_idle_user_ids",
                AsyncMock(return_value=["u1", "u2"]),
            ) as find,
            patch(f"{MODULE}.mark_sandbox_dead", AsyncMock()) as mark_dead,
        ):
            result = await sweep_idle_sandboxes({})

        after = datetime.now(UTC)
        assert result.startswith("Evicted 2 idle sandboxes (cutoff=")
        assert mark_dead.await_count == 2
        assert {c.args[0] for c in mark_dead.await_args_list} == {"u1", "u2"}

        cutoff = find.await_args.kwargs["cutoff"]
        expected_lower = before - timedelta(days=1)
        expected_upper = after - timedelta(days=1)
        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    async def test_one_failed_user_does_not_abort_the_sweep(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "E2B_SANDBOX_EVICT_DAYS", 1)

        async def mark_dead(user_id: str) -> None:
            if user_id == "bad":
                raise RuntimeError("e2b api down")

        with (
            patch(
                f"{MODULE}.e2b_sandbox_repository.find_idle_user_ids",
                AsyncMock(return_value=["ok", "bad"]),
            ),
            patch(f"{MODULE}.mark_sandbox_dead", mark_dead),
        ):
            result = await sweep_idle_sandboxes({})

        assert result.startswith("Evicted 1 idle sandboxes (cutoff=")
