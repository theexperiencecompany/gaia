"""Unit tests for ``app.memory.pg_store.graph`` — the entity register queries.

Same seam and style as ``test_memories.py``: the ``memory_session`` seam is
mocked and the built SQL is compiled against the Postgres dialect and
asserted on, so scoping is pinned without I/O.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.pg_store.graph import get_entities_by_type
from tests.unit.memory.pg_store.test_memories import _all_result, _compiled, _executed_stmts


@contextmanager
def _patched_graph_session(session: MagicMock) -> Iterator[MagicMock]:
    """Patch ``graph.memory_session`` so ``async with`` yields ``session``."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    with patch("app.memory.pg_store.graph.memory_session", return_value=ctx) as patched:
        yield patched


pytestmark = pytest.mark.unit

USER = "user-1"


class TestGetEntitiesByType:
    async def test_only_entities_with_a_live_memory_are_returned(self) -> None:
        """The register feeds the people.md rewrite, and an entity whose every
        supporting memory is gone (forgotten, superseded, expired) is exactly
        the junk that ended up listed — probed live: register-only names with
        zero facts (public figures from lookups, one bare register entry) were
        all written into the document. Live-linked is the register's meaning."""
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([]))
        with _patched_graph_session(session):
            await get_entities_by_type(USER, "person")

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        # The join columns are the register's meaning: entity -> its links ->
        # the memories those links support. Asserted ON-clause exact so a
        # flipped or rewired join cannot pass as "some join happened".
        assert "JOIN memory_entity_links ON memory_entity_links.entity_id = memory_entities.id" in (
            sql
        )
        assert "JOIN memories ON memories.id = memory_entity_links.memory_id" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        # One row per entity however many live memories support it, in the
        # alphabetical order the people.md register renders.
        assert sql.startswith("SELECT DISTINCT ")
        assert sql.rstrip().endswith("ORDER BY memory_entities.name")
        assert params["user_id_1"] == USER
        assert params["entity_type_1"] == "person"
