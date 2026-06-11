"""CRUD for the entity graph: entities, memory links, and labeled edges."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.pg_store._session import memory_session, rowcount
from app.models.memory_db_models import (
    MemoryEntity,
    MemoryEntityLink,
    MemoryGraphEdge,
    MemoryRecord,
)


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


def _canonical_pair(source_id: uuid.UUID, target_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Return the entity pair in a stable, direction-independent order.

    The alphabetically-first UUID string becomes the first element so that
    (A→B) and (B→A) are treated as the same unordered pair.
    """
    a, b = str(source_id), str(target_id)
    return (source_id, target_id) if a <= b else (target_id, source_id)


def _dedupe_edges(edges: list[MemoryGraphEdge]) -> list[MemoryGraphEdge]:
    """Collapse edges that connect the same unordered entity pair to one.

    When multiple edges exist between the same two entities (different
    relationship wording, or opposite direction), exactly one is returned —
    the one with the longest relationship label (most informative). The
    unordered pair is ONLY the dedup key: the winner keeps its original
    source/target, because a relationship label is directional ("lives in",
    "is from") and swapping endpoints to a canonical order would invert its
    meaning ("Surat is from Aryan").
    """
    best: dict[tuple[uuid.UUID, uuid.UUID], MemoryGraphEdge] = {}
    for edge in edges:
        key = _canonical_pair(edge.source_entity_id, edge.target_entity_id)
        existing = best.get(key)
        if existing is None or len(edge.relationship) > len(existing.relationship):
            best[key] = edge
    return list(best.values())


async def insert_edges(
    user_id: str,
    edges: list[tuple[uuid.UUID, str, uuid.UUID]],
    memory_id: uuid.UUID | None,
) -> int:
    """Insert (source, relationship, target) edges, skipping known triples.

    Before inserting, any edge whose unordered entity pair already has a live
    edge in the DB (regardless of direction or relationship wording) is dropped
    to prevent duplicate/reworded edges from accumulating in the graph.

    Returns how many edges were actually inserted.
    """
    if not edges:
        return 0

    # Deduplicate within the batch itself before touching the DB.
    seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    deduped_edges: list[tuple[uuid.UUID, str, uuid.UUID]] = []
    for source_id, relationship, target_id in edges:
        pair = _canonical_pair(source_id, target_id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped_edges.append((source_id, relationship, target_id))

    async with memory_session() as session:
        # Fetch every live edge among the candidate entities, then build the set
        # of unordered pairs already present. Filtering both endpoints to the
        # candidate entity ids (plain single-column IN, robust under asyncpg)
        # is enough: any edge connecting a candidate pair has both endpoints in
        # this set, and _canonical_pair makes the comparison direction-agnostic.
        candidate_entity_ids = {s for s, _, _ in deduped_edges} | {t for _, _, t in deduped_edges}
        existing_result = await session.execute(
            select(MemoryGraphEdge.source_entity_id, MemoryGraphEdge.target_entity_id).where(
                MemoryGraphEdge.user_id == user_id,
                MemoryGraphEdge.source_entity_id.in_(candidate_entity_ids),
                MemoryGraphEdge.target_entity_id.in_(candidate_entity_ids),
            )
        )
        existing_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for src, tgt in existing_result.all():
            existing_pairs.add(_canonical_pair(src, tgt))

        new_edges = [
            (s, r, t) for s, r, t in deduped_edges if _canonical_pair(s, t) not in existing_pairs
        ]
        if not new_edges:
            return 0

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
                    for source_id, relationship, target_id in new_edges
                ]
            )
            .on_conflict_do_nothing(constraint="uq_memory_graph_edges_triple")
        )
        await session.commit()
        return rowcount(result)


async def get_graph(
    user_id: str,
) -> tuple[list[tuple[MemoryEntity, int]], list[MemoryGraphEdge]]:
    """The user's graph: (entity, live-memory count) pairs and current edges.

    Counts and edges are restricted to facts that are still current
    (``is_latest`` and not forgotten). Without this, an edge from a superseded
    fact ("lives in Kolkata" after a move to Ahmedabad) would linger forever,
    so the graph showed contradictory relationships. Entities left with no live
    memories and no live edge are dropped client-side by the graph adapter.
    """
    live = (MemoryRecord.is_latest.is_(True)) & (MemoryRecord.is_forgotten.is_(False))
    async with memory_session() as session:
        entity_result = await session.execute(
            select(MemoryEntity, func.count(MemoryEntityLink.memory_id).filter(live))
            .outerjoin(MemoryEntityLink, MemoryEntityLink.entity_id == MemoryEntity.id)
            .outerjoin(MemoryRecord, MemoryRecord.id == MemoryEntityLink.memory_id)
            .where(MemoryEntity.user_id == user_id)
            .group_by(MemoryEntity.id)
            .order_by(MemoryEntity.name)
        )
        edge_result = await session.execute(
            select(MemoryGraphEdge)
            .join(MemoryRecord, MemoryRecord.id == MemoryGraphEdge.memory_id)
            .where(MemoryGraphEdge.user_id == user_id, live)
        )
        entities = [(entity, count) for entity, count in entity_result.all()]
        raw_edges = list(edge_result.scalars().all())
        return entities, _dedupe_edges(raw_edges)


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
