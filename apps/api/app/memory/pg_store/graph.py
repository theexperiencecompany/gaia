"""CRUD for the entity graph: entities, memory links, and labeled edges."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.pg_store._session import memory_session, rowcount
from app.models.memory_db_models import MemoryEntity, MemoryEntityLink, MemoryGraphEdge


def _alias_match(
    name_lower: str, entity_type: str, existing: list[MemoryEntity]
) -> MemoryEntity | None:
    """Find an existing same-type entity that is the same thing under a fuller name.

    Resolves "Khyati" against an existing "Khyati Randeriya" (and vice versa) by
    whole-word token containment: one name's words are a subset of the other's.
    This collapses first-name vs full-name duplicates into one graph node. Same
    entity_type is required so a person named "Sam" never merges into a place.
    """
    tokens = set(name_lower.split())
    if not tokens:
        return None
    best: MemoryEntity | None = None
    for entity in existing:
        if entity.entity_type != entity_type:
            continue
        other = set(entity.name_lower.split())
        if other and (tokens <= other or other <= tokens):
            # Prefer the candidate that shares the most words (most specific).
            if best is None or len(other & tokens) > len(set(best.name_lower.split()) & tokens):
                best = entity
    return best


async def upsert_entities(user_id: str, names_types: list[tuple[str, str]]) -> dict[str, uuid.UUID]:
    """Insert-or-resolve entities; return name_lower -> canonical entity id.

    Resolution order per mention: exact case-insensitive name, then an alias
    match against an existing same-type entity (first-name vs full-name), then
    create. When a fuller name arrives for an existing entity, the canonical
    name is upgraded to the fuller form so the graph shows one well-named node.
    """
    if not names_types:
        return {}

    deduped: dict[str, tuple[str, str]] = {}
    for name, entity_type in names_types:
        normalized = name.strip()
        if normalized:
            deduped.setdefault(normalized.lower(), (normalized, entity_type))

    async with memory_session() as session:
        existing = list(
            (await session.execute(select(MemoryEntity).where(MemoryEntity.user_id == user_id)))
            .scalars()
            .all()
        )
        existing_by_lower = {entity.name_lower: entity for entity in existing}

        id_map: dict[str, uuid.UUID] = {}
        to_create: list[tuple[str, str, str]] = []
        for name_lower, (name, entity_type) in deduped.items():
            exact = existing_by_lower.get(name_lower)
            if exact is not None:
                id_map[name_lower] = exact.id
                continue
            alias = _alias_match(name_lower, entity_type, existing)
            if alias is not None:
                id_map[name_lower] = alias.id
                # Upgrade to the fuller name (e.g. "Khyati" -> "Khyati Randeriya").
                if len(name) > len(alias.name):
                    alias.name = name
                    alias.name_lower = name_lower
                    existing_by_lower[name_lower] = alias
                continue
            to_create.append((name, name_lower, entity_type))

        if to_create:
            # Collapse aliases that appear together in THIS batch (e.g. both
            # "Khyati" and "Khyati Randeriya" in one extraction): the fuller name
            # wins, shorter ones map to it after insert.
            to_create.sort(key=lambda item: len(item[0]), reverse=True)
            survivors: list[tuple[str, str, str]] = []
            alias_to_survivor: dict[str, str] = {}
            for name, name_lower, entity_type in to_create:
                match = _alias_match(
                    name_lower,
                    entity_type,
                    [
                        MemoryEntity(name=sname, name_lower=snl, entity_type=setype)
                        for sname, snl, setype in survivors
                    ],
                )
                if match is not None:
                    alias_to_survivor[name_lower] = match.name_lower
                else:
                    survivors.append((name, name_lower, entity_type))

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
                        for name, name_lower, entity_type in survivors
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_memory_entities_user_name")
            )
            created = await session.execute(
                select(MemoryEntity.name_lower, MemoryEntity.id).where(
                    MemoryEntity.user_id == user_id,
                    MemoryEntity.name_lower.in_([name_lower for _, name_lower, _ in survivors]),
                )
            )
            for name_lower, entity_id in created.all():
                id_map[name_lower] = entity_id
            for alias_lower, survivor_lower in alias_to_survivor.items():
                if survivor_lower in id_map:
                    id_map[alias_lower] = id_map[survivor_lower]

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
