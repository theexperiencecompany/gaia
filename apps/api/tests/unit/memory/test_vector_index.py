"""A user's held vectors: the similarity floor, k, delta refresh on a write, and the size cap."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.memory import vector_index
from app.memory.pg_store.vectors import VectorDelta, VectorSnapshot

_READ_AT = datetime(2026, 11, 17, tzinfo=UTC)


def _unit(rows: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(rows, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def _snapshot(ids: list[str], rows: list[list[float]]) -> VectorSnapshot:
    return VectorSnapshot(ids=ids, matrix=_unit(rows), read_at=_READ_AT)


def _delta(live: list[str], rows: list[list[float]], dead: list[str] | None = None) -> VectorDelta:
    matrix = _unit(rows) if rows else np.empty((0, 0), dtype=np.float32)
    return VectorDelta(live_ids=live, matrix=matrix, dead_ids=dead or [], read_at=_READ_AT)


@pytest.fixture(autouse=True)
def _empty_index() -> None:
    vector_index._held.clear()


async def test_nearest_keeps_k_best_at_or_above_the_floor() -> None:
    snapshot = _snapshot(["a", "b", "c"], [[1, 0], [0.8, 0.6], [0, 1]])
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(return_value=snapshot)),
    ):
        found = await vector_index.nearest("u1", [1.0, 0.0], 2, min_similarity=0.5)

    assert found == ["a", "b"]


async def test_a_write_reads_only_what_changed_not_the_whole_set() -> None:
    """Ingestion bumps the version after nearly every turn; a full reload each time is MBs per turn."""
    full = AsyncMock(return_value=_snapshot(["a"], [[1, 0]]))
    changed = AsyncMock(return_value=_delta(["b"], [[0.9, 0.1]]))
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(side_effect=["1", "1", "2"])),
        patch.object(vector_index, "live_vectors", new=full),
        patch.object(vector_index, "vectors_changed_since", new=changed),
    ):
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a"]
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a"]
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a", "b"]

    assert full.await_count == 1
    assert changed.await_count == 1
    assert changed.await_args is not None
    assert changed.await_args.args[2] < _READ_AT


async def test_a_memory_that_stopped_being_live_leaves_the_held_set() -> None:
    full = AsyncMock(return_value=_snapshot(["a", "b"], [[1, 0], [0.9, 0.1]]))
    changed = AsyncMock(return_value=_delta(["a"], [[0, 1]], dead=["b"]))
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(side_effect=["1", "2"])),
        patch.object(vector_index, "live_vectors", new=full),
        patch.object(vector_index, "vectors_changed_since", new=changed),
    ):
        await vector_index.has_vectors("u1")
        found = await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=-1.0)

    assert found == ["a"]
    assert vector_index._held["u1"].matrix.shape == (1, 2)


async def test_a_set_held_past_its_full_reload_age_is_read_whole_again() -> None:
    """Hard deletes and expiry leave no changed row behind; the periodic full read drops them."""
    full = AsyncMock(return_value=_snapshot(["a"], [[1, 0]]))
    changed = AsyncMock(return_value=_delta([], []))
    with (
        patch.object(vector_index, "VECTOR_FULL_RELOAD_SECONDS", 0),
        patch.object(vector_index, "_current_version", new=AsyncMock(side_effect=["1", "2"])),
        patch.object(vector_index, "live_vectors", new=full),
        patch.object(vector_index, "vectors_changed_since", new=changed),
    ):
        await vector_index.has_vectors("u1")
        await vector_index.has_vectors("u1")

    assert full.await_count == 2
    assert changed.await_count == 0


async def test_a_load_outlasting_the_turn_budget_is_held_for_the_next_turn() -> None:
    """A heavy user's load must not restart, and be cut off again, on every turn."""
    started, release = asyncio.Event(), asyncio.Event()
    snapshot = _snapshot(["a"], [[1, 0]])

    async def slow_load(*_args: object) -> VectorSnapshot:
        started.set()
        await release.wait()
        return snapshot

    load = AsyncMock(side_effect=slow_load)
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=load),
    ):
        turn = asyncio.ensure_future(vector_index.has_vectors("u1"))
        await started.wait()
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        release.set()

        assert await vector_index.has_vectors("u1")

    assert load.await_count == 1


async def test_the_held_sets_are_capped_by_size_oldest_out_and_the_current_user_kept() -> None:
    """A user cap alone lets a few thousand heavy users hold gigabytes in one process."""
    one_row = _snapshot(["a"], [[1, 0]])
    big = _snapshot(["a", "b", "c"], [[1, 0], [0, 1], [1, 1]])
    load = AsyncMock(side_effect=[one_row, one_row, big])
    with (
        patch.object(vector_index, "VECTOR_CACHE_MAX_BYTES", one_row.matrix.nbytes * 2),
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=load),
    ):
        for user_id in ("u1", "u2", "u3"):
            await vector_index.has_vectors(user_id)

    assert list(vector_index._held) == ["u3"]
