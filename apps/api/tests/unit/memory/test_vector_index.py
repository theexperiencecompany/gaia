"""A user's held vectors: the similarity floor, k, and reload on a version change."""

from unittest.mock import AsyncMock, patch

import numpy as np

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
