"""CRUD for the episodic journal: one row per (user, local date)."""

from datetime import date as date_type

from sqlalchemy import cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.sql import func

from app.memory.pg_store._session import LIKE_ESCAPE_CHAR, escape_like, memory_session
from app.models.memory_db_models import MemoryEpisode

EpisodeEntry = dict[str, str]  # {time, text, source}


async def append_episode_entries(
    user_id: str, date: date_type, entries: list[EpisodeEntry]
) -> None:
    """Append timestamped journal lines to a day, creating the row if needed.

    Atomic upsert: concurrent ingestions concatenate instead of clobbering.
    """
    if not entries:
        return
    statement = pg_insert(MemoryEpisode).values(user_id=user_id, date=date, entries=entries)
    statement = statement.on_conflict_do_update(
        constraint="uq_memory_episodes_user_date",
        set_={
            "entries": MemoryEpisode.entries.op("||")(cast(entries, JSONB)),
            "updated_at": func.now(),
        },
    )
    async with memory_session() as session:
        await session.execute(statement)
        await session.commit()


async def get_episode(user_id: str, date: date_type) -> MemoryEpisode | None:
    """Fetch one day's journal page."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode).where(
                MemoryEpisode.user_id == user_id,
                MemoryEpisode.date == date,
            )
        )
        return result.scalar_one_or_none()


async def get_episodes_range(user_id: str, start: date_type, end: date_type) -> list[MemoryEpisode]:
    """Journal pages for a date range (inclusive), oldest first."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode)
            .where(
                MemoryEpisode.user_id == user_id,
                MemoryEpisode.date >= start,
                MemoryEpisode.date <= end,
            )
            .order_by(MemoryEpisode.date)
        )
        return list(result.scalars().all())


async def set_episode_summary(user_id: str, date: date_type, summary: str) -> None:
    """Write the lazy day-rollover summary onto a journal page."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode).where(
                MemoryEpisode.user_id == user_id,
                MemoryEpisode.date == date,
            )
        )
        episode = result.scalar_one_or_none()
        if episode is None:
            return
        episode.summary = summary
        await session.commit()


async def search_episode_entries(
    user_id: str,
    tokens: list[str],
    *,
    since: date_type,
    limit: int,
) -> list[tuple[date_type, EpisodeEntry]]:
    """Journal entries since ``since`` matching ANY query token, newest day first.

    Entries are JSONB lines inside one row per day, so FTS over them would
    need a derived index; instead each row's entries are expanded with
    ``jsonb_array_elements`` and matched with ILIKE. This is indexed-sane
    because the (indexed) ``user_id`` + ``date >= since`` filter bounds the
    expansion to at most one row per day in the window (~14 rows) before any
    ILIKE runs — a JSONB GIN index would buy nothing here.
    """
    if not tokens:
        return []
    entry = func.jsonb_array_elements(MemoryEpisode.entries).table_valued(
        "value", joins_implicitly=True
    )
    entry_text = entry.c.value.op("->>")("text")
    statement = (
        select(MemoryEpisode.date, entry.c.value)
        .where(
            MemoryEpisode.user_id == user_id,
            MemoryEpisode.date >= since,
            or_(
                *[
                    entry_text.ilike(f"%{escape_like(token)}%", escape=LIKE_ESCAPE_CHAR)
                    for token in tokens
                ]
            ),
        )
        .order_by(MemoryEpisode.date.desc())
        .limit(limit)
    )
    async with memory_session() as session:
        result = await session.execute(statement)
        return [(date, entry_value) for date, entry_value in result.all()]


async def get_unsummarized_episode_dates(user_id: str, before_date: date_type) -> list[date_type]:
    """Past days that have journal entries but no summary yet, oldest first."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode.date)
            .where(
                MemoryEpisode.user_id == user_id,
                MemoryEpisode.date < before_date,
                MemoryEpisode.summary.is_(None),
            )
            .order_by(MemoryEpisode.date)
        )
        return [date for (date,) in result.all()]
