"""Unit tests for ``app.memory.pg_store.maintenance`` — overview counts.

The ``memory_session`` seam is mocked (hermetic, no I/O); the count
statements are compiled against the Postgres dialect so the liveness and
expiry scoping is pinned to exact SQL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from app.memory.pg_store.maintenance import get_overview_counts

USER = "user-1"


@contextmanager
def _patched_memory_session(session: MagicMock) -> Iterator[MagicMock]:
    """Patch ``maintenance.memory_session`` so ``async with`` yields ``session``."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    with patch("app.memory.pg_store.maintenance.memory_session", return_value=ctx) as patched:
        yield patched


def _scalar_one_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _compiled(stmt: Select[tuple[Any, ...]]) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


@pytest.mark.unit
class TestGetOverviewCounts:
    async def _run(self) -> list[str]:
        """Run get_overview_counts; return the compiled SQL of each count query."""
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(n) for n in (5, 4, 3, 2)])
        with _patched_memory_session(session):
            counts = await get_overview_counts(USER)
        assert (counts.total_memories, counts.total_entities) == (5, 4)
        assert (counts.folder_count, counts.episode_count) == (3, 2)
        return [_compiled(call.args[0]) for call in session.execute.await_args_list]

    async def test_memory_count_excludes_forgotten_and_expired_rows(self) -> None:
        """The headline number must agree with the folder tree and the live
        cap count, which all exclude expired rows — not just forgotten ones."""
        memory_sql = (await self._run())[0]
        assert "memories.user_id = %(user_id_1)s" in memory_sql
        assert "memories.is_latest IS true" in memory_sql
        assert "memories.is_forgotten IS false" in memory_sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in memory_sql

    async def test_folder_count_excludes_forgotten_and_expired_rows(self) -> None:
        folder_sql = (await self._run())[2]
        assert "count(distinct(memories.category_path))" in folder_sql
        assert "memories.user_id = %(user_id_1)s" in folder_sql
        assert "memories.is_latest IS true" in folder_sql
        assert "memories.is_forgotten IS false" in folder_sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in folder_sql
