"""Unit tests for the nightly memory expiry sweep ARQ task."""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks import memory_sweep_tasks


@pytest.mark.unit
class TestSweepExpiredMemoriesTask:
    @staticmethod
    def _patches(owners: list[str]) -> dict[str, AsyncMock]:
        return {
            "backfill": AsyncMock(return_value=0),
            "sweep": AsyncMock(return_value=owners),
            "count": AsyncMock(return_value=3),
            "set_count": AsyncMock(return_value=None),
            "render": AsyncMock(return_value=None),
            "invalidate": AsyncMock(return_value=None),
        }

    async def _run(self, owners: list[str]) -> dict[str, AsyncMock]:
        mocks = self._patches(owners)
        with (
            patch.object(memory_sweep_tasks.pg_store, "backfill_agenda_expiry", mocks["backfill"]),
            patch.object(memory_sweep_tasks.pg_store, "sweep_expired_memories", mocks["sweep"]),
            patch.object(memory_sweep_tasks.pg_store, "count_live_memories", mocks["count"]),
            patch.object(memory_sweep_tasks, "set_cached_live_count", mocks["set_count"]),
            patch.object(memory_sweep_tasks, "render_agenda_document", mocks["render"]),
            patch.object(memory_sweep_tasks, "invalidate_user_memory_caches", mocks["invalidate"]),
        ):
            await memory_sweep_tasks.sweep_expired_memories({})
        return mocks

    @pytest.mark.regression
    async def test_legacy_agenda_rows_get_an_expiry_before_the_sweep(self) -> None:
        """Agenda rows written before the task shelf-life shipped carry no
        ``forget_after``, so the sweep never retires them — measured in
        production: 152 of 157 live agenda rows were expiry-less ``durable``
        rows, keeping year-old items in the always-injected agenda block.
        The task must stamp them BEFORE sweeping, so an already-overdue
        legacy item is retired in the same run."""
        order: list[str] = []
        mocks = self._patches(owners=[])
        mocks["backfill"].side_effect = lambda: order.append("backfill")
        mocks["sweep"].side_effect = lambda: order.append("sweep") or []
        with (
            patch.object(memory_sweep_tasks.pg_store, "backfill_agenda_expiry", mocks["backfill"]),
            patch.object(memory_sweep_tasks.pg_store, "sweep_expired_memories", mocks["sweep"]),
            patch.object(memory_sweep_tasks.pg_store, "count_live_memories", mocks["count"]),
            patch.object(memory_sweep_tasks, "set_cached_live_count", mocks["set_count"]),
            patch.object(memory_sweep_tasks, "render_agenda_document", mocks["render"]),
            patch.object(memory_sweep_tasks, "invalidate_user_memory_caches", mocks["invalidate"]),
        ):
            await memory_sweep_tasks.sweep_expired_memories({})

        assert order == ["backfill", "sweep"]

    async def test_each_affected_user_s_views_are_repaired(self) -> None:
        mocks = await self._run(owners=["u1", "u2", "u1"])

        assert mocks["render"].await_count == 2
        assert mocks["set_count"].await_count == 2
        assert mocks["invalidate"].await_count == 2
