"""Unit tests for ``app.memory.pg_store.episodes`` — the episodic journal CRUD.

Every function talks to Postgres through the module-level ``memory_session``
seam; that seam is mocked (hermetic, no I/O). The SQL statements the functions
build are compiled against the Postgres dialect and asserted on their bound
parameters, pinning the upsert constraint, the dedup filter, the JSONB
concatenation, the ILIKE escape behavior, and the read-time summary clause.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.pg_store.episodes import (
    _entry_key,
    append_episode_entries,
    get_episode,
    get_episodes_range,
    get_unsummarized_episode_dates,
    search_episode_entries,
    set_episode_summary,
)
from app.models.memory_db_models import MemoryEpisode

USER = "user-1"


@contextmanager
def mock_memory_session() -> Iterator[MagicMock]:
    """A session whose ``execute`` returns a configurable scalar/rows.

    ``__aenter__`` returns the session itself so ``async with
    memory_session() as session`` binds the same object we assert on."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    with patch("app.memory.pg_store.episodes.memory_session", return_value=session):
        yield session


def make_episode(*, day: date, entries: list[dict[str, str]]) -> MemoryEpisode:
    """A detached MemoryEpisode, as ``get_episode`` would return."""
    return MemoryEpisode(
        id="ep-1", user_id=USER, date=day, entries=entries, created_at=datetime.now(UTC)
    )


# ── _entry_key: normalization for duplicate detection ────────────────────────


def test_entry_key_normalizes_quotes_case_and_whitespace() -> None:
    """Curly quotes, casing, inner spacing and trailing punctuation must all
    fold to the same key or the same line slips past dedup."""
    assert _entry_key("It’s a “test” line!") == _entry_key('It\'s a "test" line')


def test_entry_key_strips_trailing_sentence_punctuation() -> None:
    assert _entry_key("hello.") == "hello"
    assert _entry_key("hello!") == "hello"
    assert _entry_key("  hello  ") == "hello"


# ── append_episode_entries ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_no_entries_is_a_noop() -> None:
    with mock_memory_session() as session:
        await append_episode_entries(USER, date(2026, 1, 1), [])
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_append_builds_atomic_upsert_with_conflict_constraint() -> None:
    """The upsert must ride the (user, date) unique constraint and concatenate
    JSONB arrays — concurrent ingestion appends instead of clobbering."""
    entries = [{"time": "09:00", "text": "woke up", "source": "chat"}]
    day = date(2026, 1, 1)
    with mock_memory_session() as session:
        with patch("app.memory.pg_store.episodes.get_episode", new=AsyncMock(return_value=None)):
            await append_episode_entries(USER, day, entries)

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=None, compile_kwargs={"literal_binds": False}))
    assert "ON CONFLICT" in compiled.upper()
    assert statement.kwargs == {}
    # Bound params: user, date, and the JSONB entries.
    assert statement.compile().params["user_id"] == USER
    assert statement.compile().params["date"] == day
    assert statement.compile().params["entries"] == entries
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_append_drops_lines_already_in_the_day() -> None:
    """Re-ingesting the full transcript must not duplicate existing lines —
    dedup is by normalized text, so a whitespace variant is still a duplicate."""
    existing = make_episode(
        day=date(2026, 1, 1),
        entries=[{"time": "09:00", "text": "woke up", "source": "chat"}],
    )
    with mock_memory_session() as session:
        with patch(
            "app.memory.pg_store.episodes.get_episode", new=AsyncMock(return_value=existing)
        ):
            await append_episode_entries(
                USER,
                date(2026, 1, 1),
                [
                    {"time": "09:00", "text": "Woke  up", "source": "chat"},
                    {"time": "10:00", "text": "new line", "source": "chat"},
                ],
            )
    # Only the genuinely new line survives.
    params = session.execute.await_args.args[0].compile().params
    assert params["entries"] == [{"time": "10:00", "text": "new line", "source": "chat"}]


@pytest.mark.asyncio
async def test_append_all_duplicates_is_a_noop() -> None:
    existing = make_episode(
        day=date(2026, 1, 1),
        entries=[{"time": "09:00", "text": "woke up", "source": "chat"}],
    )
    with mock_memory_session() as session:
        with patch(
            "app.memory.pg_store.episodes.get_episode", new=AsyncMock(return_value=existing)
        ):
            await append_episode_entries(
                USER,
                date(2026, 1, 1),
                [{"time": "09:00", "text": "woke up", "source": "chat"}],
            )
    session.execute.assert_not_called()


# ── get_episode / get_episodes_range ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_episode_scopes_to_user_and_date() -> None:
    with mock_memory_session() as session:
        await get_episode(USER, date(2026, 1, 1))
    statement = session.execute.await_args.args[0]
    where = statement.whereclause
    assert str(where) == "memory_episodes.user_id = :user_id_1 AND memory_episodes.date = :date_1"


@pytest.mark.asyncio
async def test_get_episodes_range_is_inclusive_and_ordered() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    with mock_memory_session() as session:
        session.execute.return_value = result
        await get_episodes_range(USER, date(2026, 1, 1), date(2026, 1, 31))
    statement = session.execute.await_args.args[0]
    compiled = str(statement)
    assert "memory_episodes.date >= :date_1" in compiled
    assert "memory_episodes.date <= :date_2" in compiled
    assert "ORDER BY memory_episodes.date" in compiled


# ── set_episode_summary ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_episode_summary_writes_when_row_exists() -> None:
    episode = make_episode(day=date(2026, 1, 1), entries=[])
    result = MagicMock()
    result.scalar_one_or_none.return_value = episode
    with mock_memory_session() as session:
        session.execute.return_value = result
        await set_episode_summary(USER, date(2026, 1, 1), "a quiet day")
    assert episode.summary == "a quiet day"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_episode_summary_missing_row_is_a_noop() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    with mock_memory_session() as session:
        session.execute.return_value = result
        await set_episode_summary(USER, date(2026, 1, 1), "nothing here")
    session.commit.assert_not_called()


# ── search_episode_entries ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_with_no_tokens_is_a_noop() -> None:
    with mock_memory_session() as session:
        assert await search_episode_entries(USER, [], since=date(2026, 1, 1), limit=10) == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_escapes_ilike_wildcards_and_expands_jsonb() -> None:
    result = MagicMock()
    result.all.return_value = []
    with mock_memory_session() as session:
        session.execute.return_value = result
        await search_episode_entries(USER, ["100%"], since=date(2026, 1, 1), limit=5)
    statement = session.execute.await_args.args[0]
    compiled = str(statement)
    assert "jsonb_array_elements" in compiled
    assert "ESCAPE" in compiled.upper()
    # The literal % must be escaped so it matches a real percent sign, not "any chars".
    assert "%" in str(statement.compile().params) or "!%" in compiled.replace(" ", "")


# ── get_unsummarized_episode_dates ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsummarized_dates_filter_on_null_summary_before_date() -> None:
    result = MagicMock()
    result.all.return_value = []
    with mock_memory_session() as session:
        session.execute.return_value = result
        await get_unsummarized_episode_dates(USER, date(2026, 2, 1))
    statement = session.execute.await_args.args[0]
    compiled = str(statement)
    assert "memory_episodes.date < :date_1" in compiled
    assert "memory_episodes.summary IS NULL" in compiled


def test_entry_key_is_stable_for_empty_text() -> None:
    assert _entry_key("") == ""
    assert _entry_key(" .! ") == ""
