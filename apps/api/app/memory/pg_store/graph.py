"""CRUD for the entity graph: entities, memory links, and labeled edges."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.pg_store._session import memory_session, rowcount
from app.models.memory_db_models import MemoryEntity, MemoryEntityLink, MemoryGraphEdge


async def upsert_entities(user_id: str, names_types: list[tuple[str, str]]) -> dict[str, uuid.UUID]:
    """Insert-or-find entities case-insensitively; return name_lower -> id.

    'Nadia' and 'nadia' resolve to the same entity via the ``name_lower``
    unique constraint; the first-seen casing of the name is kept.
    """
    if not names_types:
        return {}

    deduped: dict[str, tuple[str, str]] = {}
    for name, entity_type in names_types:
        normalized = name.strip()
        if normalized:
            deduped.setdefault(normalized.lower(), (normalized, entity_type))

    async with memory_session() as session:
        await session.execute(
            pg_insert(MemoryEntity)
            .values(
                [
                    {
                        "user_id": user_id,
                        "name": name,
                        "name_lower": name_lower,
                        "entity_type": entity_type,
                    }
                    for name_lower, (name, entity_type) in deduped.items()
                ]
            )
            .on_conflict_do_nothing(constraint="uq_memory_entities_user_name")
        )
        result = await session.execute(
            select(MemoryEntity.name_lower, MemoryEntity.id).where(
                MemoryEntity.user_id == user_id,
                MemoryEntity.name_lower.in_(deduped.keys()),
            )
        )
        id_map = {name_lower: entity_id for name_lower, entity_id in result.all()}
        await session.commit()
        return id_map


async def link_entities(memory_id: uuid.UUID, entity_ids: list[uuid.UUID]) -> None:
    """Link a memory to the entities it mentions (idempotent)."""
    if not entity_ids:
        return
    async with memory_session() as session:
        await session.execute(
            pg_insert(MemoryEntityLink)
            .values([{"memory_id": memory_id, "entity_id": entity_id} for entity_id in entity_ids])
            .on_conflict_do_nothing()
        )
        await session.commit()


async def insert_edges(
    user_id: str,
    edges: list[tuple[uuid.UUID, str, uuid.UUID]],
    memory_id: uuid.UUID | None,
) -> int:
    """Insert (source, relationship, target) edges, skipping known triples.

    Returns how many edges were actually inserted.
    """
    if not edges:
        return 0
    async with memory_session() as session:
        result = await session.execute(
            pg_insert(MemoryGraphEdge)
            .values(
                [
                    {
                        "user_id": user_id,
                        "source_entity_id": source_id,
                        "relationship": relationship,
                        "target_entity_id": target_id,
                        "memory_id": memory_id,
                    }
                    for source_id, relationship, target_id in edges
                ]
            )
            .on_conflict_do_nothing(constraint="uq_memory_graph_edges_triple")
        )
        await session.commit()
        return rowcount(result)


async def get_graph(
    user_id: str,
) -> tuple[list[tuple[MemoryEntity, int]], list[MemoryGraphEdge]]:
    """The user's full graph: (entity, linked-memory count) pairs and all edges."""
    async with memory_session() as session:
        entity_result = await session.execute(
            select(MemoryEntity, func.count(MemoryEntityLink.memory_id))
            .outerjoin(MemoryEntityLink, MemoryEntityLink.entity_id == MemoryEntity.id)
            .where(MemoryEntity.user_id == user_id)
            .group_by(MemoryEntity.id)
            .order_by(MemoryEntity.name)
        )
        edge_result = await session.execute(
            select(MemoryGraphEdge).where(MemoryGraphEdge.user_id == user_id)
        )
        entities = [(entity, count) for entity, count in entity_result.all()]
        return entities, list(edge_result.scalars().all())


async def get_entities_by_type(user_id: str, entity_type: str) -> list[MemoryEntity]:
    """A user's entities of one type (e.g. every person), alphabetical."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEntity)
            .where(
                MemoryEntity.user_id == user_id,
                MemoryEntity.entity_type == entity_type,
            )
            .order_by(MemoryEntity.name)
        )
        return list(result.scalars().all())


async def get_entities_for_memories(
    memory_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[MemoryEntity]]:
    """Entities linked to each of the given memories, keyed by memory id."""
    if not memory_ids:
        return {}
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEntityLink.memory_id, MemoryEntity)
            .join(MemoryEntity, MemoryEntity.id == MemoryEntityLink.entity_id)
            .where(MemoryEntityLink.memory_id.in_(memory_ids))
        )
        entities_by_memory: dict[uuid.UUID, list[MemoryEntity]] = {}
        for memory_id, entity in result.all():
            entities_by_memory.setdefault(memory_id, []).append(entity)
        return entities_by_memory
