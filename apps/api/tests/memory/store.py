"""Direct-store seed/inspect helpers for the memory engine suite.

Seeding goes through the production storage layer (pg_store + chroma_store
+ real fastembed embeddings) so retrieval tests exercise the same persisted
shape ingestion produces. Inspection helpers read Postgres/Chroma directly
so tests assert on persisted state, not on return values.
"""

from datetime import datetime
from typing import Any, TypedDict
import uuid

from sqlalchemy import func, select

from app.constants.memory import (
    CHROMA_MEMORIES_COLLECTION,
    MemoryKind,
    MemorySourceType,
)
from app.memory import chroma_store, pg_store
from app.memory.chroma_store import MemoryVectorItem
from app.memory.embeddings import embed_batch
from app.memory.pg_store._session import memory_session
from app.models.memory_db_models import (
    MemoryDocument,
    MemoryEntity,
    MemoryEntityLink,
    MemoryEpisode,
    MemoryGraphEdge,
    MemoryRecord,
)


class MemorySpec(TypedDict, total=False):
    """One memory to seed: content plus optional storage attributes."""

    content: str
    category: str
    kind: MemoryKind
    importance: float
    forget_after: datetime | None
    entities: list[tuple[str, str]]  # (name, entity_type)


async def seed_memories(user_id: str, specs: list[MemorySpec]) -> list[MemoryRecord]:
    """Insert memories into Postgres + Chroma exactly as ingestion would."""
    embeddings = await embed_batch([spec["content"] for spec in specs])
    records = [
        MemoryRecord(
            user_id=user_id,
            kind=spec.get("kind", MemoryKind.FACT).value,
            content=spec["content"],
            category_path=spec.get("category", "general"),
            importance=spec.get("importance", 0.5),
            forget_after=spec.get("forget_after"),
            source_type=MemorySourceType.MANUAL.value,
        )
        for spec in specs
    ]
    await pg_store.insert_memories(records)
    items: list[MemoryVectorItem] = [
        {
            "id": str(record.id),
            "embedding": embedding,
            "document": record.content,
            "metadata": {
                "user_id": user_id,
                "kind": record.kind,
                "category_path": record.category_path,
                "is_latest": True,
                "is_forgotten": False,
            },
        }
        for record, embedding in zip(records, embeddings)
    ]
    await chroma_store.upsert_memories(items)

    for spec, record in zip(specs, records):
        entities = spec.get("entities")
        if entities:
            id_map = await pg_store.upsert_entities(user_id, entities)
            await pg_store.link_entities(record.id, list(id_map.values()))
    return records


async def fetch_memory_rows(user_id: str) -> list[MemoryRecord]:
    """Every memory row for a user (including superseded/forgotten), oldest first."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord)
            .where(MemoryRecord.user_id == user_id)
            .order_by(MemoryRecord.created_at, MemoryRecord.version)
        )
        return list(result.scalars().all())


async def fetch_entities(user_id: str) -> list[MemoryEntity]:
    async with memory_session() as session:
        result = await session.execute(select(MemoryEntity).where(MemoryEntity.user_id == user_id))
        return list(result.scalars().all())


async def fetch_edges(user_id: str) -> list[MemoryGraphEdge]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryGraphEdge).where(MemoryGraphEdge.user_id == user_id)
        )
        return list(result.scalars().all())


async def fetch_episode_rows(user_id: str) -> list[MemoryEpisode]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode)
            .where(MemoryEpisode.user_id == user_id)
            .order_by(MemoryEpisode.date)
        )
        return list(result.scalars().all())


async def fetch_document_rows(user_id: str) -> list[MemoryDocument]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryDocument).where(MemoryDocument.user_id == user_id)
        )
        return list(result.scalars().all())


async def count_entity_links(user_id: str) -> int:
    """Entity links attached to a user's memories (the link table has no user_id)."""
    async with memory_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(MemoryEntityLink)
            .join(MemoryRecord, MemoryRecord.id == MemoryEntityLink.memory_id)
            .where(MemoryRecord.user_id == user_id)
        )
        return result.scalar_one()


async def linked_entity_ids(memory_id: uuid.UUID) -> set[uuid.UUID]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEntityLink.entity_id).where(MemoryEntityLink.memory_id == memory_id)
        )
        return {entity_id for (entity_id,) in result.all()}


async def chroma_user_vector_ids(
    user_id: str, collection_name: str = CHROMA_MEMORIES_COLLECTION
) -> list[str]:
    """All vector ids stored for a user in one Chroma collection."""
    collection = await chroma_store._get_collection(collection_name)
    result = await collection.get(where={"user_id": user_id})
    return list(result["ids"])


async def chroma_vector_metadata(
    vector_id: str, collection_name: str = CHROMA_MEMORIES_COLLECTION
) -> dict[str, Any] | None:
    """Metadata for one vector, or None when the vector does not exist."""
    collection = await chroma_store._get_collection(collection_name)
    result = await collection.get(ids=[vector_id], include=["metadatas"])
    metadatas = result.get("metadatas") or []
    if not result["ids"] or not metadatas:
        return None
    return dict(metadatas[0])
