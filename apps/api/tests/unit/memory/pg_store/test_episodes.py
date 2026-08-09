"""Unit tests for app.memory.pg_store.episodes — the episodic journal CRUD.

The Postgres boundary (``memory_session``) is mocked; every function builds
its real SQLAlchemy statement, which is compiled against a real PostgreSQL
dialect so both the SQL shape and the exact bound values are pinned by
assertion (``literal_binds`` can't render JSONB, so params are asserted
directly instead of inlined).
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date as date_type
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql as sa_postgresql

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
DAY = date_type(2026, 8, 9)


def _compile(statement: Any) -> tuple[str, dict[str, Any]]:
    """Render a statement with the PostgreSQL dialect: SQL text + bound params."""
    compiled = statement.compile(dialect=sa_postgresql.dialect())
    return compiled.string, compiled.params


def _episode(entries: list[dict[str, Any]], *, summary: str | None = None) -> MemoryEpisode:
    """A real ``MemoryEpisode`` row — attribute access needs no database."""
    return MemoryEpisode(user_id=USER, date=DAY, entries=entries, summary=summary)


@dataclass
class Boundaries:
    """The mocked Postgres seam, exposing the real statements it was fed."""

    execute: AsyncMock
    commit: AsyncMock

    @property
    def statements(self) -> list[Any]:
        return [call.args[0] for call in self.execute.await_args_list]

    def set_scalar(self, episode: MemoryEpisode | None) -> None:
        self.execute.return_value.scalar_one_or_none = MagicMock(return_value=episode)

    def set_scalars(self, episodes: list[MemoryEpisode]) -> None:
        self.execute.return_value.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=episodes))
        )

    def set_rows(self, rows: list[Any]) -> None:
        self.execute.return_value.all = MagicMock(return_value=rows)


@pytest.fixture
def db() -> Any:
    session = AsyncMock()

    @asynccontextmanager
    async def fake_memory_session() -> Any:
        yield session

    with patch("app.memory.pg_store.episodes.memory_session", new=fake_memory_session):
        yield Boundaries(execute=session.execute, commit=session.commit)


class TestEntryKey:
    """The journal-line normalization used for duplicate detection."""

    def test_normalizes_curly_quotes_casing_and_padding(self) -> None:
        assert _entry_key("  I’m HOME! ") == "i'm home"

    def test_normalizes_curly_double_quotes(self) -> None:
        assert _entry_key('She said “hi”') == 'she said "hi"'

    def test_strips_trailing_periods_and_exclamations(self) -> None:
        assert _entry_key("It's done.") == "it's done"


class TestAppendEpisodeEntries:
    async def test_empty_entries_returns_without_touching_db(self, db: Boundaries) -> None:
        with patch(
            "app.memory.pg_store.episodes.get_episode", new_callable=AsyncMock
        ) as mock_get:
            assert await append_episode_entries(USER, DAY, []) is None

        mock_get.assert_not_awaited()
        assert db.statements == []
        db.commit.assert_not_awaited()

    async def test_inserts_an_upsert_when_the_day_does_not_exist(
        self, db: Boundaries
    ) -> None:
        entries = [{"time": "09:00", "text": "Went for a run", "source": "fitness"}]
        with patch(
            "app.memory.pg_store.episodes.get_episode",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await append_episode_entries(USER, DAY, entries)

        sql, params = _compile(db.statements[0])
        assert sql.startswith("INSERT INTO memory_episodes")
        assert (
            "ON CONFLICT ON CONSTRAINT uq_memory_episodes_user_date "
            "DO UPDATE SET entries = (memory_episodes.entries || CAST(%(param_1)s::JSONB AS JSONB))"
            in sql
        )
        assert "updated_at = now()" in sql
        assert params["user_id"] == USER
        assert params["date"] == DAY
        assert params["entries"] == entries
        assert params["param_1"] == entries
        db.commit.assert_awaited_once()

    async def test_drops_lines_already_present_after_normalization(
        self, db: Boundaries
    ) -> None:
        existing = _episode([{"time": "09:00", "text": "Introduced myself", "source": "chat"}])
        fresh = {"time": "09:05", "text": "Asked about weekend plans", "source": "chat"}
        with patch(
            "app.memory.pg_store.episodes.get_episode",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            await append_episode_entries(
                USER,
                DAY,
                [
                    {"time": "09:02", "text": "  Introduced  myself!  ", "source": "chat"},
                    fresh,
                ],
            )

        sql, params = _compile(db.statements[0])
        assert params["entries"] == [fresh]
        assert params["param_1"] == [fresh]
        assert "Introduced" not in sql
        db.commit.assert_awaited_once()

    async def test_skips_the_upsert_when_every_line_is_already_present(
        self, db: Boundaries
    ) -> None:
        existing = _episode([{"time": "09:00", "text": "Went for a run", "source": "fitness"}])
        with patch(
            "app.memory.pg_store.episodes.get_episode",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            await append_episode_entries(
                USER, DAY, [{"time": "09:01", "text": "WENT FOR A RUN!", "source": "fitness"}]
            )

        assert db.statements == []
        db.commit.assert_not_awaited()

    async def test_entries_without_text_are_not_treated_as_duplicates(
        self, db: Boundaries
    ) -> None:
        existing = _episode([{"time": "09:00", "text": "A real line", "source": "chat"}])
        no_text = {"time": "09:05", "source": "app"}
        with patch(
            "app.memory.pg_store.episodes.get_episode",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            await append_episode_entries(USER, DAY, [no_text])

        _, params = _compile(db.statements[0])
        assert params["entries"] == [no_text]
        db.commit.assert_awaited_once()

    async def test_db_failure_propagates_without_committing(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")
        with patch(
            "app.memory.pg_store.episodes.get_episode",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="connection lost"):
                await append_episode_entries(USER, DAY, [{"text": "x", "source": "chat"}])

        db.commit.assert_not_awaited()


class TestGetEpisode:
    async def test_returns_the_day_when_it_exists(self, db: Boundaries) -> None:
        episode = _episode([{"time": "09:00", "text": "Went for a run", "source": "fitness"}])
        db.set_scalar(episode)

        result = await get_episode(USER, DAY)

        assert result is episode
        sql, params = _compile(db.statements[0])
        assert "FROM memory_episodes" in sql
        assert params["user_id_1"] == USER
        assert params["date_1"] == DAY

    async def test_returns_none_when_the_day_is_missing(self, db: Boundaries) -> None:
        db.set_scalar(None)

        assert await get_episode(USER, DAY) is None

    async def test_db_failure_propagates(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await get_episode(USER, DAY)


class TestGetEpisodesRange:
    async def test_returns_days_oldest_first_with_inclusive_bounds(
        self, db: Boundaries
    ) -> None:
        episodes = [_episode([]), _episode([])]
        db.set_scalars(episodes)
        start, end = date_type(2026, 8, 1), date_type(2026, 8, 9)

        result = await get_episodes_range(USER, start, end)

        assert result == episodes
        sql, params = _compile(db.statements[0])
        assert "memory_episodes.user_id = %(user_id_1)s" in sql
        assert "memory_episodes.date >= %(date_1)s" in sql
        assert "memory_episodes.date <= %(date_2)s" in sql
        assert "ORDER BY memory_episodes.date" in sql
        assert params["user_id_1"] == USER
        assert params["date_1"] == start
        assert params["date_2"] == end

    async def test_returns_empty_list_when_no_days_match(self, db: Boundaries) -> None:
        db.set_scalars([])

        assert (
            await get_episodes_range(USER, date_type(2026, 8, 1), date_type(2026, 8, 9))
            == []
        )

    async def test_db_failure_propagates(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await get_episodes_range(USER, date_type(2026, 8, 1), date_type(2026, 8, 9))


class TestSetEpisodeSummary:
    async def test_writes_the_summary_onto_the_found_day(self, db: Boundaries) -> None:
        episode = _episode([], summary=None)
        db.set_scalar(episode)

        assert await set_episode_summary(USER, DAY, "A calm, slow day.") is None

        assert episode.summary == "A calm, slow day."
        db.commit.assert_awaited_once()

    async def test_is_a_noop_when_the_day_does_not_exist(self, db: Boundaries) -> None:
        db.set_scalar(None)

        await set_episode_summary(USER, DAY, "A calm, slow day.")

        db.commit.assert_not_awaited()

    async def test_db_failure_propagates(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await set_episode_summary(USER, DAY, "A calm, slow day.")


class TestSearchEpisodeEntries:
    async def test_empty_tokens_returns_without_touching_db(self, db: Boundaries) -> None:
        assert await search_episode_entries(USER, [], since=DAY, limit=10) == []
        assert db.statements == []

    async def test_returns_matches_for_any_token_newest_day_first(
        self, db: Boundaries
    ) -> None:
        rows = [
            (
                date_type(2026, 8, 9),
                {"time": "09:00", "text": "ran 5k", "source": "fitness"},
            ),
            (
                date_type(2026, 8, 7),
                {"time": "18:00", "text": "cooked 100% whole wheat", "source": "app"},
            ),
        ]
        db.set_rows(rows)

        result = await search_episode_entries(
            USER, ["ran", "100%"], since=date_type(2026, 8, 1), limit=5
        )

        assert result == rows
        sql, params = _compile(db.statements[0])
        assert "jsonb_array_elements(memory_episodes.entries)" in sql
        assert "(anon_1.value ->> %(value_1)s) ILIKE %(param_1)s ESCAPE '\\\\'" in sql
        assert "(anon_1.value ->> %(value_1)s) ILIKE %(param_2)s ESCAPE '\\\\'" in sql
        assert "ORDER BY memory_episodes.date DESC" in sql
        assert "LIMIT %(param_3)s" in sql
        assert params["user_id_1"] == USER
        assert params["date_1"] == date_type(2026, 8, 1)
        assert params["value_1"] == "text"
        assert params["param_1"] == "%ran%"
        assert params["param_2"] == "%100\\%%"
        assert params["param_3"] == 5

    async def test_wildcards_in_tokens_are_escaped_to_match_literally(
        self, db: Boundaries
    ) -> None:
        db.set_rows([])

        await search_episode_entries(USER, ["100%_done"], since=DAY, limit=10)

        _, params = _compile(db.statements[0])
        assert params["param_1"] == "%100\\%\\_done%"

    async def test_db_failure_propagates(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await search_episode_entries(USER, ["ran"], since=DAY, limit=10)


class TestGetUnsummarizedEpisodeDates:
    async def test_returns_past_days_without_a_summary_oldest_first(
        self, db: Boundaries
    ) -> None:
        dates = [date_type(2026, 8, 1), date_type(2026, 8, 3)]
        db.set_rows([(date,) for date in dates])

        result = await get_unsummarized_episode_dates(USER, date_type(2026, 8, 9))

        assert result == dates
        sql, params = _compile(db.statements[0])
        assert "memory_episodes.date < %(date_1)s" in sql
        assert "memory_episodes.summary IS NULL" in sql
        assert "ORDER BY memory_episodes.date" in sql
        assert params["user_id_1"] == USER
        assert params["date_1"] == date_type(2026, 8, 9)

    async def test_returns_empty_when_every_day_is_summarized(self, db: Boundaries) -> None:
        db.set_rows([])

        assert await get_unsummarized_episode_dates(USER, date_type(2026, 8, 9)) == []

    async def test_db_failure_propagates(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await get_unsummarized_episode_dates(USER, date_type(2026, 8, 9))
