"""CRUD for the canonical ``memories`` table.

Purely storage: no LLM calls, no embedding calls. Lineage rules live here
(supersession chains, soft forgetting, the read-time ``forget_after``
filter); everything semantic happens upstream in the engine.
"""

from datetime import UTC, datetime
import uuid

from sqlalchemy import ColumnElement, Select, func, select, update

from app.constants.memory import MemoryRelationType
from app.memory.pg_store._session import memory_session, rowcount
from app.models.memory_db_models import MemoryEntityLink, MemoryRecord


def _not_expired_clause() -> ColumnElement[bool]:
    """Read-time expiry filter: ``forget_after`` is enforced on read, never swept."""
    return (MemoryRecord.forget_after.is_(None)) | (MemoryRecord.forget_after > datetime.now(UTC))


def _active_memories_query(user_id: str) -> Select[tuple[MemoryRecord]]:
    """Base query for live memories: latest, not forgotten, not expired."""
    return select(MemoryRecord).where(
        MemoryRecord.user_id == user_id,
        MemoryRecord.is_latest.is_(True),
        MemoryRecord.is_forgotten.is_(False),
        _not_expired_clause(),
    )


async def insert_memories(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """Bulk-insert new memory rows and return them with ids populated."""
    if not records:
        return []
    async with memory_session() as session:
        session.add_all(records)
        await session.commit()
    return records


async def get_memory(memory_id: str, user_id: str) -> MemoryRecord | None:
    """Fetch one memory by id, scoped to its owner."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == uuid.UUID(memory_id),
                MemoryRecord.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


async def get_memories_by_ids(user_id: str, memory_ids: list[str]) -> list[MemoryRecord]:
    """Fetch multiple memories by id, scoped to their owner."""
    if not memory_ids:
        return []
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord).where(
                MemoryRecord.id.in_([uuid.UUID(memory_id) for memory_id in memory_ids]),
                MemoryRecord.user_id == user_id,
            )
        )
        return list(result.scalars().all())


async def supersede_memory(
    old_id: str,
    user_id: str,
    new_record: MemoryRecord,
    relation_type: MemoryRelationType = MemoryRelationType.UPDATES,
) -> MemoryRecord | None:
    """Chain a new version onto an existing memory, transactionally.

    Inserts ``new_record`` with lineage derived from the old row
    (version+1, parent, root, relation) and flips the old row's
    ``is_latest`` to False. Returns the new row, or None when the old
    memory does not exist for this user.
    """
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == uuid.UUID(old_id),
                MemoryRecord.user_id == user_id,
            )
        )
        old = result.scalar_one_or_none()
        if old is None:
            return None

        new_record.user_id = user_id
        new_record.version = old.version + 1
        new_record.parent_id = old.id
        new_record.root_id = old.root_id or old.id
        new_record.relation_type = relation_type.value
        old.is_latest = False
        session.add(new_record)
        await session.commit()
    return new_record


async def mark_forgotten(memory_id: str, user_id: str, reason: str) -> bool:
    """Soft-delete a memory. Returns False when it does not exist."""
    async with memory_session() as session:
        result = await session.execute(
            update(MemoryRecord)
            .where(
                MemoryRecord.id == uuid.UUID(memory_id),
                MemoryRecord.user_id == user_id,
            )
            .values(is_forgotten=True, forget_reason=reason)
        )
        await session.commit()
        return rowcount(result) > 0


async def list_memories(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    include_subfolders: bool = False,
    include_superseded: bool = False,
) -> tuple[list[MemoryRecord], int]:
    """One page of a user's memories, newest first, with the total count.

    ``category`` matches the folder exactly (tree expansion shows only a
    folder's own memories); ``include_subfolders=True`` widens it to a
    prefix match over the whole subtree.
    """
    filters: list[ColumnElement[bool]] = [
        MemoryRecord.user_id == user_id,
        MemoryRecord.is_forgotten.is_(False),
        _not_expired_clause(),
    ]
    if not include_superseded:
        filters.append(MemoryRecord.is_latest.is_(True))
    if category:
        category_filter = MemoryRecord.category_path == category
        if include_subfolders:
            category_filter = category_filter | MemoryRecord.category_path.like(f"{category}/%")
        filters.append(category_filter)

    async with memory_session() as session:
        total = (
            await session.execute(select(func.count()).select_from(MemoryRecord).where(*filters))
        ).scalar_one()
        result = await session.execute(
            select(MemoryRecord)
            .where(*filters)
            .order_by(MemoryRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total


async def fts_search(user_id: str, query: str, limit: int) -> list[tuple[MemoryRecord, float]]:
    """Weighted full-text search over live memories, best match first.

    Uses ``websearch_to_tsquery`` so user-style queries (quoted phrases,
    ``-exclusions``) work, ranked by ``ts_rank_cd`` over the weighted
    ``search_tsv`` column.
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(MemoryRecord.search_tsv, tsquery)
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord, rank)
            .where(
                MemoryRecord.user_id == user_id,
                MemoryRecord.is_latest.is_(True),
                MemoryRecord.is_forgotten.is_(False),
                _not_expired_clause(),
                MemoryRecord.search_tsv.op("@@")(tsquery),
            )
            .order_by(rank.desc())
            .limit(limit)
        )
        return [(row[0], float(row[1])) for row in result.all()]


async def get_memories_for_entities(
    user_id: str,
    entity_ids: list[uuid.UUID],
    exclude_memory_ids: list[uuid.UUID],
    limit: int,
) -> list[MemoryRecord]:
    """Live memories linked to any of the entities, most important first.

    Powers 1-hop graph expansion in recall: the entities on the top results
    pull in sibling memories that mention the same people/places/projects.
    """
    if not entity_ids:
        return []
    query = (
        _active_memories_query(user_id)
        .join(MemoryEntityLink, MemoryEntityLink.memory_id == MemoryRecord.id)
        .where(MemoryEntityLink.entity_id.in_(entity_ids))
        .distinct()
        .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
        .limit(limit)
    )
    if exclude_memory_ids:
        query = query.where(MemoryRecord.id.not_in(exclude_memory_ids))
    async with memory_session() as session:
        result = await session.execute(query)
        return list(result.scalars().all())


async def get_folder_tree(user_id: str) -> list[tuple[str, int]]:
    """All category paths with live-memory counts, alphabetical."""
    async with memory_session() as session:
        result = await session.execute(
            _active_memories_query(user_id)
            .with_only_columns(MemoryRecord.category_path, func.count())
            .group_by(MemoryRecord.category_path)
            .order_by(MemoryRecord.category_path)
        )
        return [(path, count) for path, count in result.all()]


async def get_recent_facts(user_id: str, limit: int = 10) -> list[str]:
    """Contents of the most recently stored live memories, newest first."""
    async with memory_session() as session:
        result = await session.execute(
            _active_memories_query(user_id)
            .with_only_columns(MemoryRecord.content)
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        )
        return [content for (content,) in result.all()]
