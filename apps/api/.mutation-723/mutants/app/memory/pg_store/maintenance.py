"""Whole-store maintenance: overview counts and the hard wipe."""

from dataclasses import dataclass

from sqlalchemy import delete, func, select

from app.memory.pg_store._session import memory_session, rowcount
from app.models.memory_db_models import (
    MemoryDocument,
    MemoryEntity,
    MemoryEntityLink,
    MemoryEpisode,
    MemoryGraphEdge,
    MemoryRecord,
)


@dataclass
class MemoryOverviewCounts:
    """Headline numbers for the settings-UI overview."""

    total_memories: int
    total_entities: int
    folder_count: int
    episode_count: int


async def get_overview_counts(user_id: str) -> MemoryOverviewCounts:
    """Count live memories, entities, folders and journal days."""
    async with memory_session() as session:
        total_memories = (
            await session.execute(
                select(func.count())
                .select_from(MemoryRecord)
                .where(
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.is_latest.is_(True),
                    MemoryRecord.is_forgotten.is_(False),
                )
            )
        ).scalar_one()
        total_entities = (
            await session.execute(
                select(func.count())
                .select_from(MemoryEntity)
                .where(MemoryEntity.user_id == user_id)
            )
        ).scalar_one()
        folder_count = (
            await session.execute(
                select(func.count(func.distinct(MemoryRecord.category_path))).where(
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.is_latest.is_(True),
                    MemoryRecord.is_forgotten.is_(False),
                )
            )
        ).scalar_one()
        episode_count = (
            await session.execute(
                select(func.count())
                .select_from(MemoryEpisode)
                .where(MemoryEpisode.user_id == user_id)
            )
        ).scalar_one()
    return MemoryOverviewCounts(
        total_memories=total_memories,
        total_entities=total_entities,
        folder_count=folder_count,
        episode_count=episode_count,
    )


async def delete_all_memories(user_id: str) -> int:
    """Hard-wipe every memory table for a user. Returns deleted memory count.

    One transaction. Links cascade from memories/entities; edges are
    deleted explicitly first so provenance FKs never dangle mid-wipe.
    """
    async with memory_session() as session:
        await session.execute(delete(MemoryGraphEdge).where(MemoryGraphEdge.user_id == user_id))
        await session.execute(
            delete(MemoryEntityLink).where(
                MemoryEntityLink.memory_id.in_(
                    select(MemoryRecord.id).where(MemoryRecord.user_id == user_id)
                )
            )
        )
        deleted = await session.execute(delete(MemoryRecord).where(MemoryRecord.user_id == user_id))
        await session.execute(delete(MemoryEntity).where(MemoryEntity.user_id == user_id))
        await session.execute(delete(MemoryEpisode).where(MemoryEpisode.user_id == user_id))
        await session.execute(delete(MemoryDocument).where(MemoryDocument.user_id == user_id))
        await session.commit()
        return rowcount(deleted)
