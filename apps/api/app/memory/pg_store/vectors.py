"""Hosted-model memory vectors in Postgres: the fast lane's semantic source."""

from collections.abc import Sequence
import uuid

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.pg_store._session import memory_session
from app.memory.pg_store.memories import _not_expired_clause
from app.models.memory_db_models import MemoryRecord, MemoryVector

Matrix = NDArray[np.float32]


def pack(vector: Sequence[float]) -> bytes:
    """Encode a vector as unit-normalised little-endian float32 bytes."""
    array: Matrix = np.asarray(vector, dtype="<f4")
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
                set_={"vector": statement.excluded.vector},
            )
        )
        await session.commit()


async def live_vectors(user_id: str, model: str) -> tuple[list[str], Matrix]:
    """Return the ids and stacked unit vectors of the user's live memories under model."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryVector.memory_id, MemoryVector.vector)
            .join(MemoryRecord, MemoryRecord.id == MemoryVector.memory_id)
            .where(
                MemoryVector.user_id == user_id,
                MemoryVector.model == model,
                MemoryRecord.is_latest.is_(True),
                MemoryRecord.is_forgotten.is_(False),
                _not_expired_clause(),
            )
        )
        rows = result.all()
    if not rows:
        return [], np.empty((0, 0), dtype=np.float32)
    ids = [str(memory_id) for memory_id, _ in rows]
    matrix = np.vstack([np.frombuffer(blob, dtype="<f4") for _, blob in rows]).astype(np.float32)
    return ids, matrix


async def live_memories_without_vector(
    model: str, after: uuid.UUID | None, limit: int
) -> list[MemoryRecord]:
    """Live memories with no vector under model, in id order from after — the backfill's cursor."""
    missing = (
        ~select(MemoryVector.memory_id)
        .where(MemoryVector.memory_id == MemoryRecord.id, MemoryVector.model == model)
        .exists()
    )
    query = select(MemoryRecord).where(
        MemoryRecord.is_latest.is_(True), MemoryRecord.is_forgotten.is_(False), missing
    )
    if after is not None:
        query = query.where(MemoryRecord.id > after)
    async with memory_session() as session:
        result = await session.execute(query.order_by(MemoryRecord.id).limit(limit))
        return list(result.scalars().all())
