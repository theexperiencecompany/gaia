"""Each active user's memory vectors, held in process and matched with one dot product.

A user has at most a few thousand memories, so their whole vector set fits in
a few MB and a brute-force match takes well under a millisecond — no ANN index
and no network hop. Every memory write bumps a version in Redis; a process whose
held version is stale reads only the rows changed since its last read, so writes
from the API and the background worker are both seen on the next turn.
"""

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import functools
import time
import uuid

import numpy as np

from app.constants.memory import (
    MEMORY_VECTOR_MODEL,
    MEMORY_VECTORS_VERSION_KEY,
    VECTOR_CACHE_MAX_BYTES,
    VECTOR_DELTA_OVERLAP_SECONDS,
    VECTOR_FULL_RELOAD_SECONDS,
)
from app.db.redis import redis_cache
from app.memory import hosted_embeddings
from app.memory.pg_store.vectors import (
    Matrix,
    VectorDelta,
    live_vectors,
    upsert_vectors,
    vectors_changed_since,
)
from app.utils.request_coalescing import coalesce_request
from shared.py.wide_events import log


@dataclass(frozen=True)
class _UserVectors:
    version: str
    ids: list[str]
    matrix: Matrix
    #: Database time the last read started; the next delta reads from just before it.
    read_at: datetime
    #: Monotonic time of the last full read.
    full_at: float


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


def _apply(held: _UserVectors, delta: VectorDelta, version: str) -> _UserVectors:
    changed = set(delta.live_ids) | set(delta.dead_ids)
    keep = [i for i, memory_id in enumerate(held.ids) if memory_id not in changed]
    kept = held.matrix[keep]
    parts = [part for part in (kept, delta.matrix) if part.size]
    return _UserVectors(
        version=version,
        ids=[held.ids[i] for i in keep] + delta.live_ids,
        matrix=np.vstack(parts) if parts else delta.matrix,
        read_at=delta.read_at,
        full_at=held.full_at,
    )


async def _load(user_id: str, version: str, previous: _UserVectors | None) -> _UserVectors:
    """Refresh and hold the user's set; held here, so a turn that stops waiting still keeps it."""
    if previous is None or time.monotonic() - previous.full_at > VECTOR_FULL_RELOAD_SECONDS:
        snapshot = await live_vectors(user_id, MEMORY_VECTOR_MODEL)
        held = _UserVectors(
            version=version,
            ids=snapshot.ids,
            matrix=snapshot.matrix,
            read_at=snapshot.read_at,
            full_at=time.monotonic(),
        )
    else:
        since = previous.read_at - timedelta(seconds=VECTOR_DELTA_OVERLAP_SECONDS)
        held = _apply(
            previous,
            await vectors_changed_since(user_id, MEMORY_VECTOR_MODEL, since),
            version,
        )
    _held[user_id] = held
    return held


async def _user_vectors(user_id: str) -> _UserVectors:
    version = await _current_version(user_id)
    held = _held.get(user_id)
    if held is None or held.version != version:
        # Coalesced: a heavy user's load can outlast the fast lane's budget, and
        # restarting it on every turn would cut it off on every turn.
        held = await coalesce_request(
            f"memory_vectors:{user_id}:{version}",
            functools.partial(_load, user_id, version, held),
        )
    _held.move_to_end(user_id)
    held_bytes = sum(entry.matrix.nbytes for entry in _held.values())
    while len(_held) > 1 and held_bytes > VECTOR_CACHE_MAX_BYTES:
        _, evicted = _held.popitem(last=False)  # pragma: no mutate — None pops oldest too
        held_bytes -= evicted.matrix.nbytes
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
    # float32 keeps the product in the matrix's dtype instead of upcasting a copy of it.
    unit = np.asarray(query, dtype=np.float32)  # pragma: no mutate — same scores, a copy
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
