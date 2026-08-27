"""Unit tests for the nightly memory expiry sweep ARQ task."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.memory.pg_store.memories import SweptMemory
from app.workers.tasks import memory_sweep_tasks


@pytest.mark.unit
class TestSweepExpiredMemoriesTask:
    @staticmethod
    def _patches(swept: list[SweptMemory]) -> dict[str, AsyncMock | MagicMock]:
        return {
            "backfill": AsyncMock(return_value=0),
            "sweep": AsyncMock(return_value=swept),
            "flags": AsyncMock(return_value=None),
            "count": AsyncMock(return_value=3),
            "set_count": AsyncMock(return_value=None),
            "render": AsyncMock(return_value=None),
            "invalidate": AsyncMock(return_value=None),
            "log": MagicMock(),
        }

    @staticmethod
    async def _run_with(mocks: dict[str, AsyncMock | MagicMock]) -> str:
        with (
            patch.object(memory_sweep_tasks.pg_store, "backfill_agenda_expiry", mocks["backfill"]),
            patch.object(memory_sweep_tasks.pg_store, "sweep_expired_memories", mocks["sweep"]),
            patch.object(memory_sweep_tasks.chroma_store, "set_memory_flags", mocks["flags"]),
            patch.object(memory_sweep_tasks.pg_store, "count_live_memories", mocks["count"]),
            patch.object(memory_sweep_tasks, "set_cached_live_count", mocks["set_count"]),
            patch.object(memory_sweep_tasks, "render_agenda_document", mocks["render"]),
            patch.object(memory_sweep_tasks, "invalidate_user_memory_caches", mocks["invalidate"]),
            patch.object(memory_sweep_tasks, "log", mocks["log"]),
        ):
            return await memory_sweep_tasks.sweep_expired_memories({})

    async def _run(self, swept: list[SweptMemory]) -> dict[str, AsyncMock | MagicMock]:
        mocks = self._patches(swept)
        await self._run_with(mocks)
        return mocks

    async def test_legacy_agenda_rows_get_an_expiry_before_the_sweep(self) -> None:
        """Agenda rows written before the task shelf-life shipped carry no
        ``forget_after``, so the sweep never retires them — measured in
        production: 152 of 157 live agenda rows were expiry-less ``durable``
        rows, keeping year-old items in the always-injected agenda block.
        The task must stamp them BEFORE sweeping, so an already-overdue
        legacy item is retired in the same run."""
        order: list[str] = []
        mocks = self._patches(swept=[])
        mocks["backfill"].side_effect = lambda: order.append("backfill")
        mocks["sweep"].side_effect = lambda: order.append("sweep") or []
        await self._run_with(mocks)

        assert order == ["backfill", "sweep"]

    async def test_swept_rows_get_their_chroma_flags_retired(self) -> None:
        """Postgres flips ``is_forgotten`` but Chroma kept ``is_latest=True,
        is_forgotten=False``, so reconciliation still matched the swept row and
        swallowed identical restatements as DUPLICATE forever. Every swept id
        must have its Chroma flags synced in the same run."""
        mocks = await self._run(
            swept=[
                SweptMemory(user_id="u1", memory_id="m1"),
                SweptMemory(user_id="u2", memory_id="m2"),
            ]
        )

        assert mocks["flags"].await_args_list == [
            call("m1", is_latest=False, is_forgotten=True),
            call("m2", is_latest=False, is_forgotten=True),
        ]

    async def test_summary_reaches_the_wide_event_and_the_return_value(self) -> None:
        """The run's outcome is reported twice — ``memory_sweep`` on the wide
        event and the ARQ result string — and both must carry the real counts
        under the names dashboards query."""
        mocks = self._patches(
            swept=[
                SweptMemory(user_id="u1", memory_id="m1"),
                SweptMemory(user_id="u2", memory_id="m2"),
                SweptMemory(user_id="u1", memory_id="m3"),
            ]
        )
        result = await self._run_with(mocks)

        assert result == "expired=3 users=2"
        mocks["log"].set.assert_called_once_with(
            memory_sweep={"memories_expired": 3, "users_repaired": 2}
        )

    async def test_each_affected_user_s_views_are_repaired(self) -> None:
        mocks = await self._run(
            swept=[
                SweptMemory(user_id="u1", memory_id="m1"),
                SweptMemory(user_id="u2", memory_id="m2"),
                SweptMemory(user_id="u1", memory_id="m3"),
            ]
        )

        assert mocks["render"].await_count == 2
        assert mocks["set_count"].await_count == 2
        assert mocks["invalidate"].await_count == 2
