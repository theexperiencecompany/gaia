"""A user's held vectors: the similarity floor, k, delta refresh on a write, and the size cap."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.constants.memory import MEMORY_VECTOR_MODEL, VECTOR_DELTA_OVERLAP_SECONDS
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


async def test_a_query_is_normalised_before_the_similarity_floor() -> None:
    """An unnormalised query would inflate every score past the floor."""
    snapshot = _snapshot(["a"], [[0.6, 0.8]])
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(return_value=snapshot)),
    ):
        assert await vector_index.nearest("u1", [3.0, 0.0], 1, min_similarity=0.9) == []


async def test_a_memory_exactly_at_the_floor_is_kept() -> None:
    snapshot = _snapshot(["a"], [[1, 0]])
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(return_value=snapshot)),
    ):
        assert await vector_index.nearest("u1", [1.0, 0.0], 1, min_similarity=1.0) == ["a"]


async def test_each_read_is_for_this_user_and_model_from_just_before_the_last_read() -> None:
    later = _READ_AT + timedelta(hours=1)
    full = AsyncMock(return_value=_snapshot(["a"], [[1, 0]]))
    first = _delta(["b"], [[0, 1]])
    changed = AsyncMock(
        side_effect=[
            VectorDelta(first.live_ids, first.matrix, first.dead_ids, read_at=later),
            _delta([], []),
        ]
    )
    version = AsyncMock(side_effect=["1", "2", "2", "3"])
    overlap = timedelta(seconds=VECTOR_DELTA_OVERLAP_SECONDS)
    with (
        patch.object(vector_index, "_current_version", new=version),
        patch.object(vector_index, "live_vectors", new=full),
        patch.object(vector_index, "vectors_changed_since", new=changed),
    ):
        for _ in range(4):
            await vector_index.has_vectors("u1")

    version.assert_awaited_with("u1")
    full.assert_awaited_once_with("u1", MEMORY_VECTOR_MODEL)
    assert [c.args for c in changed.await_args_list] == [
        ("u1", MEMORY_VECTOR_MODEL, _READ_AT - overlap),
        ("u1", MEMORY_VECTOR_MODEL, later - overlap),
    ]


async def test_a_set_exactly_at_its_full_reload_age_still_reads_only_the_delta() -> None:
    full = AsyncMock(return_value=_snapshot(["a"], [[1, 0]]))
    changed = AsyncMock(return_value=_delta([], []))
    with (
        patch.object(vector_index, "VECTOR_FULL_RELOAD_SECONDS", 0),
        patch("app.memory.vector_index.time", SimpleNamespace(monotonic=lambda: 100.0)),
        patch.object(vector_index, "_current_version", new=AsyncMock(side_effect=["1", "2"])),
        patch.object(vector_index, "live_vectors", new=full),
        patch.object(vector_index, "vectors_changed_since", new=changed),
    ):
        await vector_index.has_vectors("u1")
        await vector_index.has_vectors("u1")

    assert full.await_count == 1
    assert changed.await_count == 1


async def test_two_users_loading_at_once_each_get_their_own_set() -> None:
    sets = {"u1": _snapshot(["a"], [[1, 0]]), "u2": _snapshot(["b"], [[0, 1]])}
    release = asyncio.Event()

    async def load(user_id: str, _model: str) -> VectorSnapshot:
        await release.wait()
        return sets[user_id]

    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(side_effect=load)),
    ):
        both = asyncio.gather(
            vector_index.nearest("u1", [1.0, 1.0], 5, min_similarity=-1.0),
            vector_index.nearest("u2", [1.0, 1.0], 5, min_similarity=-1.0),
        )
        await asyncio.sleep(0)
        release.set()

        assert await both == [["a"], ["b"]]


async def test_eviction_stops_once_the_held_sets_fit() -> None:
    one_row = _snapshot(["a"], [[1, 0]])
    with (
        patch.object(vector_index, "VECTOR_CACHE_MAX_BYTES", one_row.matrix.nbytes * 2),
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(return_value=one_row)),
    ):
        for user_id in ("u1", "u2", "u3"):
            await vector_index.has_vectors(user_id)

    assert list(vector_index._held) == ["u2", "u3"]
