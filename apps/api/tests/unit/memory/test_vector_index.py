"""A user's held vectors: the similarity floor, k, and reload on a version change."""

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.memory import vector_index


def _held(ids: list[str], rows: list[list[float]]) -> tuple[list[str], np.ndarray]:
    matrix = np.asarray(rows, dtype=np.float32)
    return ids, matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


async def test_nearest_keeps_k_best_at_or_above_the_floor() -> None:
    vector_index._held.clear()
    ids, matrix = _held(["a", "b", "c"], [[1, 0], [0.8, 0.6], [0, 1]])
    with (
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=AsyncMock(return_value=(ids, matrix))),
    ):
        found = await vector_index.nearest("u1", [1.0, 0.0], 2, min_similarity=0.5)

    assert found == ["a", "b"]


async def test_a_new_version_reloads_the_set_and_the_same_version_does_not() -> None:
    vector_index._held.clear()
    first = _held(["a"], [[1, 0]])
    second = _held(["a", "b"], [[1, 0], [0.9, 0.1]])
    load = AsyncMock(side_effect=[first, second])
    version = AsyncMock(side_effect=["1", "1", "2"])
    with (
        patch.object(vector_index, "_current_version", new=version),
        patch.object(vector_index, "live_vectors", new=load),
    ):
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a"]
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a"]
        assert await vector_index.nearest("u1", [1.0, 0.0], 5, min_similarity=0.0) == ["a", "b"]

    assert load.await_count == 2


async def test_a_load_outlasting_the_turn_budget_is_held_for_the_next_turn() -> None:
    """A heavy user's load must not restart, and be cut off again, on every turn."""
    vector_index._held.clear()
    started, release = asyncio.Event(), asyncio.Event()
    ids, matrix = _held(["a"], [[1, 0]])

    async def slow_load(*_args: object) -> tuple[list[str], np.ndarray]:
        started.set()
        await release.wait()
        return ids, matrix

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
    vector_index._held.clear()
    one_row = _held(["a"], [[1, 0]])
    big = _held(["a", "b", "c"], [[1, 0], [0, 1], [1, 1]])
    load = AsyncMock(side_effect=[one_row, one_row, big])
    with (
        patch.object(vector_index, "VECTOR_CACHE_MAX_BYTES", one_row[1].nbytes * 2),
        patch.object(vector_index, "_current_version", new=AsyncMock(return_value="1")),
        patch.object(vector_index, "live_vectors", new=load),
    ):
        for user_id in ("u1", "u2", "u3"):
            await vector_index.has_vectors(user_id)

    assert list(vector_index._held) == ["u3"]
