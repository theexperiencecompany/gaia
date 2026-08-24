"""The stale-spawn sweep: age from uuid6 checkpoint ids, prefix selection, caps.

Spawn threads embed a LIVE conversation's uuid, so the orphan sweep can never
reclaim them — this third phase is their only collector. Its two sharp edges are
pinned here: the age comes from decoding the uuid6 checkpoint id (there is no
timestamp column), and the ``spawn_`` prefix contains ``_``, a LIKE wildcard
that must be escaped or ``spawnXanything`` matches too.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.base.id import uuid6
import pytest

from app.workers.tasks import checkpoint_retention_tasks as tasks
from app.workers.tasks.checkpoint_retention_tasks import (
    _checkpoint_written_at,
    prune_checkpoint_versions,
    sweep_stale_spawn_threads,
)

_GREGORIAN_EPOCH = datetime(1582, 10, 15, tzinfo=UTC)


def uuid6_aged(days_ago: float) -> str:
    """A uuid6 whose embedded timestamp lies ``days_ago`` in the past."""
    ticks = int(
        (datetime.now(UTC) - timedelta(days=days_ago) - _GREGORIAN_EPOCH).total_seconds()
        * 10_000_000
    )
    high, mid, low = (ticks >> 28) & 0xFFFFFFFF, (ticks >> 12) & 0xFFFF, ticks & 0x0FFF
    return f"{high:08x}-{mid:04x}-6{low:03x}-8001-4f618c253aee"


class FakeCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    async def fetchall(self) -> list[tuple[str, str]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> "FakeConnection":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakePool:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def connection(self) -> FakeConnection:
        return FakeConnection(self._cursor)


class FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class TestCheckpointWrittenAt:
    def test_a_real_uuid6_decodes_to_its_mint_time(self) -> None:
        # The saver's own generator, not a hand-rolled id — if LangGraph ever
        # changes the id scheme, this is the test that must notice.
        written = _checkpoint_written_at(str(uuid6(clock_seq=1)))

        assert written is not None
        assert abs((datetime.now(UTC) - written).total_seconds()) < 60

    def test_ids_that_carry_no_timestamp_read_as_unknown_not_a_wrong_date(self) -> None:
        assert _checkpoint_written_at("7c9e6679-7425-40de-944b-e07fc1f90ae7") is None  # uuid4
        assert _checkpoint_written_at("not-a-uuid") is None
        assert _checkpoint_written_at(None) is None


class TestSweepStaleSpawnThreads:
    async def test_deletes_only_threads_older_than_the_retention_window(self) -> None:
        cursor = FakeCursor(
            [
                ("spawn_conv1_old", uuid6_aged(30)),
                ("spawn_conv2_just_stale", uuid6_aged(8)),
                ("spawn_conv3_fresh", uuid6_aged(0)),
                ("spawn_conv4_unreadable", "not-a-uuid"),
            ]
        )
        checkpointer = FakeCheckpointer()

        result = await sweep_stale_spawn_threads(FakePool(cursor), checkpointer)

        assert sorted(checkpointer.deleted) == ["spawn_conv1_old", "spawn_conv2_just_stale"]
        assert result == {"spawn_threads_total": 4, "spawn_threads_deleted": 2}

    async def test_the_like_pattern_escapes_the_underscore_wildcard(self) -> None:
        # Without ESCAPE, `spawn_%` also matches `spawnX...` — `_` is a wildcard.
        cursor = FakeCursor([])

        await sweep_stale_spawn_threads(FakePool(cursor), FakeCheckpointer())

        sql, params = cursor.executed[0]
        assert "ESCAPE" in sql
        assert params == ("spawn!_%",)

    async def test_deletions_per_run_are_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tasks, "CHECKPOINT_SPAWN_SWEEP_MAX_THREADS", 1)
        cursor = FakeCursor([("spawn_a_1", uuid6_aged(30)), ("spawn_b_2", uuid6_aged(30))])
        checkpointer = FakeCheckpointer()

        result = await sweep_stale_spawn_threads(FakePool(cursor), checkpointer)

        assert len(checkpointer.deleted) == 1
        assert result["spawn_threads_deleted"] == 1


class TestNightlyJobComposition:
    async def test_the_nightly_job_runs_all_three_phases(self) -> None:
        # The cron table wires the job; this pins that the job itself still calls
        # every phase — the stale-spawn sweep has no other trigger.
        manager = SimpleNamespace(pool=object(), get_checkpointer=lambda: object())
        orphan = AsyncMock(
            return_value={
                "threads_total": 5,
                "orphan_threads_deleted": 1,
                "orphan_checkpoints_deleted": 3,
            }
        )
        spawn = AsyncMock(return_value={"spawn_threads_total": 4, "spawn_threads_deleted": 2})
        prune = AsyncMock(
            return_value={
                "threads_pruned": 6,
                "checkpoints_deleted": 7,
                "writes_deleted": 0,
                "blobs_deleted": 0,
                "bytes_estimate": 8,
            }
        )

        with (
            patch.object(tasks, "get_checkpointer_manager", AsyncMock(return_value=manager)),
            patch.object(tasks, "sweep_orphan_threads", orphan),
            patch.object(tasks, "sweep_stale_spawn_threads", spawn),
            patch.object(tasks, "prune_thread_versions", prune),
        ):
            summary = await prune_checkpoint_versions({})

        orphan.assert_awaited_once()
        spawn.assert_awaited_once()
        prune.assert_awaited_once()
        assert "stale_spawns=2" in summary
