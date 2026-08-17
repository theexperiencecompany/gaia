"""Unit tests for app.workers.tasks.session_tasks.

``prune_inactive_sessions`` deletes on-disk chat session directories inactive
past the retention window — the backstop for sessions whose conversation was
deleted while JuiceFS was unreachable. Per-session failures are logged and
must never abort the rest of the batch.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
from app.workers.tasks.session_tasks import prune_inactive_sessions

MODULE = "app.workers.tasks.session_tasks"


class TestPruneInactiveSessions:
    async def test_prunes_every_stale_session(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "SESSION_RETENTION_DAYS", 30)
        monkeypatch.setattr(settings, "SESSION_PRUNE_BATCH_LIMIT", 1000)
        with (
            patch(
                f"{MODULE}.list_stale_sessions",
                AsyncMock(return_value=[("u1", "c1"), ("u2", "c2")]),
            ) as list_stale,
            patch(f"{MODULE}.delete_session_dir", AsyncMock()) as delete,
            patch(f"{MODULE}.flush_fs_metrics", MagicMock(return_value=None)),
        ):
            result = await prune_inactive_sessions({})

        assert result == "pruned 2/2 sessions (cutoff=30d)"
        assert delete.await_count == 2
        assert {tuple(c.args) for c in delete.await_args_list} == {("u1", "c1"), ("u2", "c2")}
        list_stale.assert_awaited_once_with(30, limit=1000)

    async def test_a_failed_session_does_not_abort_the_batch(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "SESSION_RETENTION_DAYS", 30)
        monkeypatch.setattr(settings, "SESSION_PRUNE_BATCH_LIMIT", 1000)

        async def delete(user_id: str, conv_id: str) -> None:
            if conv_id == "bad":
                raise RuntimeError("juicefs unreachable")

        with (
            patch(
                f"{MODULE}.list_stale_sessions",
                AsyncMock(return_value=[("u1", "ok"), ("u1", "bad")]),
            ),
            patch(f"{MODULE}.delete_session_dir", delete),
            patch(f"{MODULE}.flush_fs_metrics", MagicMock(return_value=None)),
        ):
            result = await prune_inactive_sessions({})

        assert result == "pruned 1/2 sessions (cutoff=30d)"

    async def test_no_stale_sessions(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "SESSION_RETENTION_DAYS", 7)
        monkeypatch.setattr(settings, "SESSION_PRUNE_BATCH_LIMIT", 5)
        with (
            patch(f"{MODULE}.list_stale_sessions", AsyncMock(return_value=[])) as list_stale,
            patch(f"{MODULE}.delete_session_dir", AsyncMock()) as delete,
            patch(f"{MODULE}.flush_fs_metrics", MagicMock(return_value=None)),
        ):
            result = await prune_inactive_sessions({})

        assert result == "pruned 0/0 sessions (cutoff=7d)"
        list_stale.assert_awaited_once_with(7, limit=5)
        delete.assert_not_awaited()

    async def test_a_stale_listing_failure_propagates(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "SESSION_RETENTION_DAYS", 30)
        monkeypatch.setattr(settings, "SESSION_PRUNE_BATCH_LIMIT", 1000)
        with (
            patch(
                f"{MODULE}.list_stale_sessions",
                AsyncMock(side_effect=RuntimeError("mount missing")),
            ),
            pytest.raises(RuntimeError, match="mount missing"),
        ):
            await prune_inactive_sessions({})
