"""Unit tests for app.memory.pg_store.maintenance — overview counts and the hard wipe.

The Postgres boundary (``memory_session``) is mocked; the four count queries
and the six-statement wipe transaction are executed with their real
SQLAlchemy statements so the filters (user scoping, live/latest flags,
distinct folders, provenance-safe delete order) are pinned by assertion, not
by eyeballing the source.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.pg_store.maintenance import (
    MemoryOverviewCounts,
    delete_all_memories,
    get_overview_counts,
)

USER = "user-1"


def _result(value: int) -> MagicMock:
    """A ``session.execute`` result whose ``scalar_one`` resolves to ``value``."""
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _sql(statement: Any) -> str:
    """Render a SQLAlchemy statement with bound values inlined, for assertion."""
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@dataclass
class Boundaries:
    """The mocked Postgres seam, exposing the real statements it was fed."""

    execute: AsyncMock
    commit: AsyncMock

    @property
    def statements(self) -> list[Any]:
        return [call.args[0] for call in self.execute.await_args_list]

    def set_counts(self, *values: int) -> None:
        self.execute.side_effect = [_result(value) for value in values]

    def set_rowcount(self, count: int) -> None:
        deleted = MagicMock()
        deleted.rowcount = count
        self.execute.side_effect = (
            [MagicMock() for _ in range(2)] + [deleted] + [MagicMock() for _ in range(3)]
        )


@pytest.fixture
def db() -> Any:
    session = AsyncMock()

    @asynccontextmanager
    async def fake_memory_session() -> Any:
        yield session

    with patch("app.memory.pg_store.maintenance.memory_session", new=fake_memory_session):
        yield Boundaries(execute=session.execute, commit=session.commit)


class TestGetOverviewCounts:
    async def test_returns_all_four_counts(self, db: Boundaries) -> None:
        db.set_counts(12, 4, 3, 21)

        counts = await get_overview_counts(USER)

        assert counts == MemoryOverviewCounts(
            total_memories=12, total_entities=4, folder_count=3, episode_count=21
        )
        assert len(db.statements) == 4

    async def test_memory_and_folder_counts_only_cover_live_latest_memories(
        self, db: Boundaries
    ) -> None:
        db.set_counts(0, 0, 0, 0)

        await get_overview_counts(USER)

        memory_sql, entity_sql, folder_sql, episode_sql = (
            _sql(statement) for statement in db.statements
        )
        for sql in (memory_sql, folder_sql):
            assert "FROM memories" in sql
            assert "memories.is_latest IS true" in sql
            assert "memories.is_forgotten IS false" in sql
        assert "FROM memory_entities" in entity_sql
        assert "is_latest" not in entity_sql
        assert "FROM memory_episodes" in episode_sql
        assert "is_latest" not in episode_sql

    async def test_folder_count_counts_distinct_category_paths(self, db: Boundaries) -> None:
        db.set_counts(0, 0, 0, 0)

        await get_overview_counts(USER)

        assert "count(distinct(memories.category_path))" in _sql(db.statements[2])

    async def test_every_query_is_scoped_to_the_user(self, db: Boundaries) -> None:
        db.set_counts(1, 2, 3, 4)

        await get_overview_counts(USER)

        for statement in db.statements:
            assert f"user_id = '{USER}'" in _sql(statement)

    async def test_zero_counts_when_nothing_is_stored(self, db: Boundaries) -> None:
        db.set_counts(0, 0, 0, 0)

        counts = await get_overview_counts(USER)

        assert counts == MemoryOverviewCounts(0, 0, 0, 0)

    async def test_db_failures_propagate(self, db: Boundaries) -> None:
        db.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await get_overview_counts(USER)


class TestDeleteAllMemories:
    async def test_returns_the_deleted_memory_rowcount(self, db: Boundaries) -> None:
        db.set_rowcount(7)

        deleted = await delete_all_memories(USER)

        assert deleted == 7
        assert len(db.statements) == 6
        db.commit.assert_awaited_once()

    async def test_returns_zero_when_nothing_was_deleted(self, db: Boundaries) -> None:
        db.set_rowcount(0)

        assert await delete_all_memories(USER) == 0

    async def test_deletes_every_table_in_provenance_safe_order(self, db: Boundaries) -> None:
        db.set_rowcount(0)

        await delete_all_memories(USER)

        sqls = [_sql(statement) for statement in db.statements]
        assert "DELETE FROM memory_graph_edges" in sqls[0]
        assert "DELETE FROM memory_entity_links" in sqls[1]
        assert "DELETE FROM memories" in sqls[2]
        assert "DELETE FROM memory_entities" in sqls[3]
        assert "DELETE FROM memory_episodes" in sqls[4]
        assert "DELETE FROM memory_documents" in sqls[5]

    async def test_entity_links_are_scoped_to_the_users_memory_ids(self, db: Boundaries) -> None:
        db.set_rowcount(0)

        await delete_all_memories(USER)

        links_sql = _sql(db.statements[1])
        assert "memory_entity_links.memory_id IN (SELECT memories.id" in links_sql
        assert f"memories.user_id = '{USER}'" in links_sql

    async def test_every_delete_is_scoped_to_the_user(self, db: Boundaries) -> None:
        db.set_rowcount(0)

        await delete_all_memories(USER)

        for statement in db.statements:
            sql = _sql(statement)
            assert f"user_id = '{USER}'" in sql
            assert "user_id = 'someone-else'" not in sql

    async def test_failed_delete_propagates_without_committing(self, db: Boundaries) -> None:
        db.execute.side_effect = [MagicMock(), RuntimeError("foreign key violation")]

        with pytest.raises(RuntimeError, match="foreign key violation"):
            await delete_all_memories(USER)

        db.commit.assert_not_awaited()

    async def test_commit_failure_propagates(self, db: Boundaries) -> None:
        db.set_rowcount(3)
        db.commit.side_effect = RuntimeError("transaction aborted")

        with pytest.raises(RuntimeError, match="transaction aborted"):
            await delete_all_memories(USER)
