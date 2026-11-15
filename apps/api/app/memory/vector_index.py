"""Each active user's memory vectors, held in process and matched with one dot product.

A user has at most a few thousand memories, so their whole vector set fits in
a few MB and a brute-force match takes well under a millisecond — no ANN index
and no network hop. Every memory write bumps a version in Redis; a process
reloads a user's set when the version it holds is stale, so writes from the API
and the background worker are both seen on the next turn.
"""

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
import uuid

import numpy as np

from app.constants.memory import (
    MEMORY_VECTOR_MODEL,
    MEMORY_VECTORS_VERSION_KEY,
    VECTOR_CACHE_MAX_USERS,
)
from app.db.redis import redis_cache
from app.memory import hosted_embeddings
from app.memory.pg_store.vectors import Matrix, live_vectors, upsert_vectors
from shared.py.wide_events import log


@dataclass(frozen=True)
class _UserVectors:
    version: str
    ids: list[str]
    matrix: Matrix


_held: OrderedDict[str, _UserVectors] = OrderedDict()


async def bump_version(user_id: str) -> None:
    """Mark the user's vector set changed, so every process reloads it."""
    if redis_cache.client:
        await redis_cache.client.incr(MEMORY_VECTORS_VERSION_KEY.format(user_id=user_id))


async def _current_version(user_id: str) -> str:
    if not redis_cache.client:
        return ""
    raw = await redis_cache.client.get(MEMORY_VECTORS_VERSION_KEY.format(user_id=user_id))
    return str(raw or "0")


async def _user_vectors(user_id: str) -> _UserVectors:
    version = await _current_version(user_id)
    held = _held.get(user_id)
    if held is None or held.version != version:
        ids, matrix = await live_vectors(user_id, MEMORY_VECTOR_MODEL)
        held = _UserVectors(version=version, ids=ids, matrix=matrix)
        _held[user_id] = held
    _held.move_to_end(user_id)
    while len(_held) > VECTOR_CACHE_MAX_USERS:
        _held.popitem(last=False)
    return held


async def has_vectors(user_id: str) -> bool:
    """Whether the user has any live memory vector under the current model."""
    return bool((await _user_vectors(user_id)).ids)


async def nearest(
    user_id: str, query: Sequence[float], k: int, *, min_similarity: float
) -> list[str]:
    """Return the ids of the user's k most similar live memories at or above min_similarity."""
    held = await _user_vectors(user_id)
    if not held.ids:
        return []
    unit = np.asarray(query, dtype=np.float32)
    scores = held.matrix @ (unit / np.linalg.norm(unit))
    top = np.argsort(-scores)[:k]
    return [held.ids[i] for i in top if scores[i] >= min_similarity]


async def index_memories(user_id: str, memories: Sequence[tuple[uuid.UUID, str]]) -> None:
    """Store hosted-model vectors for freshly written memories.

    The memory rows are already committed and stay the source of truth, so a
    failure here is logged and left for the backfill, which picks up every live
    memory without a vector, rather than failing the write that produced it.
    """
    if not memories or not hosted_embeddings.configured():
        return
    try:
        vectors = await hosted_embeddings.embed_documents([content for _, content in memories])
        await upsert_vectors(
            user_id,
            MEMORY_VECTOR_MODEL,
            [(memory_id, vector) for (memory_id, _), vector in zip(memories, vectors, strict=True)],
        )
    except Exception as e:
        log.error(
            "Indexing memory vectors failed; the backfill repairs it",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            memory_count=len(memories),
        )
