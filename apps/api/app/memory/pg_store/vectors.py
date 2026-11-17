"""Hosted-model memory vectors in Postgres: the fast lane's semantic source."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import uuid

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import ColumnElement, Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.pg_store._session import memory_session
from app.memory.pg_store.memories import _not_expired_clause
from app.models.memory_db_models import MemoryRecord, MemoryVector

Matrix = NDArray[np.float32]


@dataclass(frozen=True)
class VectorSnapshot:
    """A user's live vectors, and the database time the read started."""

    ids: list[str]
    matrix: Matrix
    read_at: datetime


@dataclass(frozen=True)
class VectorDelta:
    """What changed since a time: live vectors to add or replace, ids no longer live."""

    live_ids: list[str]
    matrix: Matrix
    dead_ids: list[str]
    read_at: datetime


def _is_live() -> ColumnElement[bool]:
    return (
        MemoryRecord.is_latest.is_(True)
        & MemoryRecord.is_forgotten.is_(False)
        & _not_expired_clause()
    )


def _stack(blobs: Sequence[bytes]) -> Matrix:
    if not blobs:
        return np.empty((0, 0), dtype=np.float32)
    return np.vstack([np.frombuffer(blob, dtype="<f4") for blob in blobs]).astype(np.float32)


def pack(vector: Sequence[float]) -> bytes:
    """Encode a vector as unit-normalised little-endian float32 bytes."""
    array = np.asarray(vector)
    unit: Matrix = (array / np.linalg.norm(array)).astype("<f4")
    return bytes(unit.tobytes())


async def upsert_vectors(
    user_id: str, model: str, vectors: Sequence[tuple[uuid.UUID, Sequence[float]]]
) -> None:
    """Store (memory_id, vector) pairs under model, replacing any earlier vector."""
    if not vectors:
        return
    rows = [
        {"memory_id": memory_id, "model": model, "user_id": user_id, "vector": pack(vector)}
        for memory_id, vector in vectors
    ]
    statement = pg_insert(MemoryVector).values(rows)
    async with memory_session() as session:
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[MemoryVector.memory_id, MemoryVector.model],
                set_={"vector": statement.excluded.vector, "updated_at": func.now()},
            )
        )
        await session.commit()


async def live_vectors(user_id: str, model: str) -> VectorSnapshot:
    """Return the ids and stacked unit vectors of the user's live memories under model."""
    async with memory_session() as session:
        read_at = (await session.execute(select(func.now()))).scalar_one()
        result = await session.execute(
            select(MemoryVector.memory_id, MemoryVector.vector)
            .join(MemoryRecord)
            .where(MemoryVector.user_id == user_id, MemoryVector.model == model, _is_live())
        )
        rows = result.all()
    return VectorSnapshot(
        ids=[str(memory_id) for memory_id, _ in rows],
        matrix=_stack([blob for _, blob in rows]),
        read_at=read_at,
    )


async def vectors_changed_since(user_id: str, model: str, since: datetime) -> VectorDelta:
    """Return the user's vectors, or their memories, changed after since, split by liveness."""
    async with memory_session() as session:
        read_at = (await session.execute(select(func.now()))).scalar_one()
        result = await session.execute(
            select(MemoryVector.memory_id, MemoryVector.vector, _is_live())
            .join(MemoryRecord)
            .where(
                MemoryVector.user_id == user_id,
                MemoryVector.model == model,
                (MemoryVector.updated_at > since) | (MemoryRecord.updated_at > since),
            )
        )
        rows: Sequence[Row[tuple[uuid.UUID, bytes, bool]]] = result.all()
    live = [(str(memory_id), blob) for memory_id, blob, is_live in rows if is_live]
    return VectorDelta(
        live_ids=[memory_id for memory_id, _ in live],
        matrix=_stack([blob for _, blob in live]),
        dead_ids=[str(memory_id) for memory_id, _, is_live in rows if not is_live],
        read_at=read_at,
    )


async def live_memories_without_vector(
    model: str, after: uuid.UUID | None, limit: int
) -> list[MemoryRecord]:
    """Live memories with no vector under model, in id order from after — the backfill's cursor."""
    has_vector = (
        select(MemoryVector.memory_id)
        .where(MemoryVector.memory_id == MemoryRecord.id, MemoryVector.model == model)
        .exists()
    )
    query = select(MemoryRecord).where(
        MemoryRecord.is_latest.is_(True), MemoryRecord.is_forgotten.is_(False), ~has_vector
    )
    if after is not None:
        query = query.where(MemoryRecord.id > after)
    async with memory_session() as session:
        result = await session.execute(query.order_by(MemoryRecord.id).limit(limit))
        return list(result.scalars().all())
