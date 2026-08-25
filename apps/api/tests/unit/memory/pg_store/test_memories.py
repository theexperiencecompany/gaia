"""Unit tests for ``app.memory.pg_store.memories`` — CRUD over the memories table.

Every function talks to Postgres through the module-level ``memory_session``
seam; that seam is mocked (hermetic, no I/O). The SQL statements the functions
build are compiled against the Postgres dialect and asserted on their bound
parameters, so scoping (owner + live filters), lineage wiring, pagination,
ordering, and the read-time expiry clause are pinned to exact values.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from sqlalchemy import Select, Update
from sqlalchemy.dialects import postgresql

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    FORGET_REASON_MAX_CHARS,
    MemoryRelationType,
)
from app.memory.pg_store._session import escape_like
from app.memory.pg_store.memories import (
    _active_memories_query,
    _not_expired_clause,
    count_live_memories,
    fts_search,
    get_agenda_memories,
    get_all_live_memories,
    get_chain,
    get_facts_for_consolidation,
    get_folder_tree,
    get_memories_by_ids,
    get_memories_for_entities,
    get_memory,
    get_recent_facts,
    insert_memories,
    list_memories,
    mark_forgotten,
    supersede_memory,
    sweep_expired_memories,
)
from app.models.memory_db_models import MemoryRecord

USER = "user-1"


def make_record(
    *,
    memory_id: uuid.UUID | None = None,
    user_id: str = USER,
    version: int = 1,
    parent_id: uuid.UUID | None = None,
    root_id: uuid.UUID | None = None,
    relation_type: str | None = None,
    is_latest: bool = True,
) -> MemoryRecord:
    """A detached MemoryRecord — no session, no DB."""
    now = datetime.now(UTC)
    return MemoryRecord(
        id=memory_id or uuid.uuid4(),
        user_id=user_id,
        kind="fact",
        content="a fact",
        category_path="work",
        importance=0.5,
        version=version,
        parent_id=parent_id,
        root_id=root_id,
        relation_type=relation_type,
        is_latest=is_latest,
        is_forgotten=False,
        forget_after=None,
        mentioned_at=now,
        created_at=now,
        updated_at=now,
        source_type="conversation",
        metadata_json={},
    )


@contextmanager
def _patched_memory_session(session: MagicMock) -> Iterator[MagicMock]:
    """Patch ``memories.memory_session`` so ``async with`` yields ``session``."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    with patch("app.memory.pg_store.memories.memory_session", return_value=ctx) as patched:
        yield patched


def _scalars_result(rows: list[MemoryRecord]) -> MagicMock:
    """A result whose ``.scalars().all()`` returns ``rows``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _all_result(rows: list[tuple[Any, ...]]) -> MagicMock:
    """A result whose ``.all()`` returns ``rows``."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def _scalar_one_result(value: Any) -> MagicMock:
    """A result whose ``.scalar_one()`` returns ``value``."""
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _compiled(stmt: Select | Update) -> tuple[str, dict[str, Any]]:
    """Compile a statement against Postgres: (sql text, bound params)."""
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def _executed_stmts(session: MagicMock) -> list[Select | Update]:
    """The statements passed to ``session.execute``, in call order."""
    return [call.args[0] for call in session.execute.await_args_list]


def _param_values(params: dict[str, Any], prefix: str) -> list[Any]:
    """All bound-param values whose bind names start with ``prefix``."""
    return [value for key, value in params.items() if key.startswith(prefix)]


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------


class TestNotExpiredClause:
    def test_keeps_nulls_and_future_dates(self) -> None:
        sql, params = _compiled(_not_expired_clause())
        assert "memories.forget_after IS NULL" in sql
        assert "memories.forget_after >" in sql
        (expiry,) = params.values()
        assert isinstance(expiry, datetime)
        assert expiry.tzinfo is not None


class TestActiveMemoriesQuery:
    def test_filters_to_live_memories_of_user(self) -> None:
        sql, params = _compiled(_active_memories_query(USER))
        assert "memories.user_id = %(user_id_1)s" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["user_id_1"] == USER


# ---------------------------------------------------------------------------
# insert_memories
# ---------------------------------------------------------------------------


class TestInsertMemories:
    async def test_empty_list_returns_empty_without_touching_session(self) -> None:
        session = MagicMock()
        with _patched_memory_session(session) as patched:
            result = await insert_memories([])

        assert result == []
        patched.assert_not_called()

    async def test_adds_all_and_commits(self) -> None:
        session = MagicMock()
        session.commit = AsyncMock()
        records = [make_record(), make_record()]
        with _patched_memory_session(session):
            result = await insert_memories(records)

        assert result is records
        session.add_all.assert_called_once_with(records)
        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# count_live_memories
# ---------------------------------------------------------------------------


class TestCountLiveMemories:
    async def test_returns_count_over_live_memories(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalar_one_result(7))
        with _patched_memory_session(session):
            count = await count_live_memories(USER)

        assert count == 7
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "count(*) AS count_1" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["user_id_1"] == USER


# ---------------------------------------------------------------------------
# get_memory
# ---------------------------------------------------------------------------


class TestGetMemory:
    async def test_returns_record_scoped_to_owner(self) -> None:
        memory_id = uuid.uuid4()
        record = make_record(memory_id=memory_id)
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            got = await get_memory(str(memory_id), USER)

        assert got is record
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.id = %(id_1)s::UUID" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert params["id_1"] == memory_id
        assert params["user_id_1"] == USER

    async def test_returns_none_when_missing(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            got = await get_memory(str(uuid.uuid4()), USER)

        assert got is None

    async def test_invalid_uuid_propagates_value_error(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock()
        with _patched_memory_session(session):
            with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
                await get_memory("not-a-uuid", USER)

        session.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_chain
# ---------------------------------------------------------------------------


class TestGetChain:
    async def test_empty_when_memory_does_not_exist(self) -> None:
        session = MagicMock()
        with (
            patch(
                "app.memory.pg_store.memories.get_memory",
                new=AsyncMock(return_value=None),
            ) as mock_get_memory,
            _patched_memory_session(session) as patched,
        ):
            chain = await get_chain(str(uuid.uuid4()), USER)

        assert chain == []
        mock_get_memory.assert_awaited_once()
        patched.assert_not_called()

    async def test_roots_chain_at_head_when_it_has_no_root(self) -> None:
        memory_id = uuid.uuid4()
        head = make_record(memory_id=memory_id, root_id=None)
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([head]))
        with (
            patch("app.memory.pg_store.memories.get_memory", new=AsyncMock(return_value=head)),
            _patched_memory_session(session),
        ):
            chain = await get_chain(str(memory_id), USER)

        assert chain == [head]
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.user_id = %(user_id_1)s" in sql
        assert "memories.id = %(id_1)s::UUID OR memories.root_id = %(root_id_1)s::UUID" in sql
        assert "ORDER BY memories.version DESC" in sql
        assert params["id_1"] == memory_id
        assert params["root_id_1"] == memory_id

    async def test_roots_chain_at_head_root_id(self) -> None:
        memory_id = uuid.uuid4()
        root_id = uuid.uuid4()
        head = make_record(memory_id=memory_id, root_id=root_id)
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with (
            patch("app.memory.pg_store.memories.get_memory", new=AsyncMock(return_value=head)),
            _patched_memory_session(session),
        ):
            chain = await get_chain(str(memory_id), USER)

        assert chain == []
        (stmt,) = _executed_stmts(session)
        _, params = _compiled(stmt)
        assert params["id_1"] == root_id
        assert params["root_id_1"] == root_id


# ---------------------------------------------------------------------------
# get_memories_by_ids
# ---------------------------------------------------------------------------


class TestGetMemoriesByIds:
    async def test_empty_ids_returns_empty_without_touching_session(self) -> None:
        session = MagicMock()
        with _patched_memory_session(session) as patched:
            result = await get_memories_by_ids(USER, [])

        assert result == []
        patched.assert_not_called()

    async def test_returns_rows_scoped_to_owner(self) -> None:
        memory_id_a = uuid.uuid4()
        memory_id_b = uuid.uuid4()
        rows = [make_record(memory_id=memory_id_a), make_record(memory_id=memory_id_b)]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result(rows))
        with _patched_memory_session(session):
            got = await get_memories_by_ids(USER, [str(memory_id_a), str(memory_id_b)])

        assert got == rows
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.id IN" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert params["id_1"] == [memory_id_a, memory_id_b]
        assert params["user_id_1"] == USER


# ---------------------------------------------------------------------------
# supersede_memory
# ---------------------------------------------------------------------------


class TestSupersedeMemory:
    async def test_returns_none_without_side_effects_when_old_missing(self) -> None:
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        new_record = make_record()
        with _patched_memory_session(session):
            got = await supersede_memory(str(uuid.uuid4()), USER, new_record)

        assert got is None
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    async def test_wires_lineage_and_flips_old_latest(self) -> None:
        old_id = uuid.uuid4()
        new_id = uuid.uuid4()
        old = make_record(memory_id=old_id, version=3, root_id=None)
        new_record = make_record(memory_id=new_id, user_id="someone-else", version=99)
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = old
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            got = await supersede_memory(str(old_id), USER, new_record)

        assert got is new_record
        assert new_record.user_id == USER
        assert new_record.version == 4
        assert new_record.parent_id == old_id
        assert new_record.root_id == old_id
        assert new_record.relation_type == MemoryRelationType.UPDATES.value
        assert old.is_latest is False
        session.add.assert_called_once_with(new_record)
        session.commit.assert_awaited_once()
        (select_stmt,) = _executed_stmts(session)
        sql, params = _compiled(select_stmt)
        assert "memories.id = %(id_1)s::UUID" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert params["id_1"] == old_id
        assert params["user_id_1"] == USER

    async def test_preserves_existing_root(self) -> None:
        old_id = uuid.uuid4()
        root_id = uuid.uuid4()
        old = make_record(memory_id=old_id, version=1, root_id=root_id)
        new_record = make_record()
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = old
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            await supersede_memory(str(old_id), USER, new_record)

        assert new_record.version == 2
        assert new_record.parent_id == old_id
        assert new_record.root_id == root_id

    async def test_applies_custom_relation_type(self) -> None:
        old = make_record(version=1, root_id=None)
        new_record = make_record(relation_type=MemoryRelationType.DERIVES.value)
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = old
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            await supersede_memory(
                str(old.id), USER, new_record, relation_type=MemoryRelationType.EXTENDS
            )

        assert new_record.relation_type == MemoryRelationType.EXTENDS.value


# ---------------------------------------------------------------------------
# mark_forgotten
# ---------------------------------------------------------------------------


class TestMarkForgotten:
    async def test_returns_true_when_row_updated(self) -> None:
        memory_id = uuid.uuid4()
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            forgotten = await mark_forgotten(str(memory_id), USER, "stale")

        assert forgotten is True
        session.commit.assert_awaited_once()
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert sql.startswith("UPDATE memories SET")
        assert "memories.id = %(id_1)s::UUID" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert params["is_forgotten"] is True
        assert params["forget_reason"] == "stale"
        assert params["id_1"] == memory_id
        assert params["user_id_1"] == USER

    async def test_returns_false_when_no_row_matched(self) -> None:
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            forgotten = await mark_forgotten(str(uuid.uuid4()), USER, "stale")

        assert forgotten is False
        session.commit.assert_awaited_once()

    async def test_truncates_reason_to_max_chars(self) -> None:
        session = MagicMock()
        session.commit = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute = AsyncMock(return_value=result)
        with _patched_memory_session(session):
            await mark_forgotten(str(uuid.uuid4()), USER, "x" * (FORGET_REASON_MAX_CHARS + 50))

        (stmt,) = _executed_stmts(session)
        _, params = _compiled(stmt)
        assert params["forget_reason"] == "x" * FORGET_REASON_MAX_CHARS


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------


class TestListMemories:
    async def test_returns_rows_and_total_newest_first(self) -> None:
        rows = [make_record(), make_record()]
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(42), _scalars_result(rows)])
        with _patched_memory_session(session):
            got_rows, total = await list_memories(USER)

        assert got_rows == rows
        assert total == 42
        count_stmt, rows_stmt = _executed_stmts(session)
        count_sql, count_params = _compiled(count_stmt)
        assert "count(*) AS count_1" in count_sql
        rows_sql, rows_params = _compiled(rows_stmt)
        for sql, params in ((count_sql, count_params), (rows_sql, rows_params)):
            assert "memories.user_id = %(user_id_1)s" in sql
            assert "memories.is_latest IS true" in sql
            assert "memories.is_forgotten IS false" in sql
            assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
            assert params["user_id_1"] == USER
        assert "ORDER BY memories.created_at DESC" in rows_sql
        assert "LIMIT" in rows_sql
        assert rows_params["param_1"] == 20
        assert rows_params["param_2"] == 0

    async def test_paginates(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(0), _scalars_result([])])
        with _patched_memory_session(session):
            await list_memories(USER, page=3, page_size=10)

        _, rows_stmt = _executed_stmts(session)
        _, params = _compiled(rows_stmt)
        assert params["param_1"] == 10
        assert params["param_2"] == 20

    async def test_category_matches_folder_exactly_by_default(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(0), _scalars_result([])])
        with _patched_memory_session(session):
            await list_memories(USER, category="work")

        _, rows_stmt = _executed_stmts(session)
        sql, params = _compiled(rows_stmt)
        assert "memories.category_path = %(category_path_1)s" in sql
        assert "LIKE" not in sql
        assert params["category_path_1"] == "work"

    async def test_subfolder_prefix_matches_and_escapes_like_metacharacters(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(0), _scalars_result([])])
        with _patched_memory_session(session):
            await list_memories(USER, category="work%dev", include_subfolders=True)

        _, rows_stmt = _executed_stmts(session)
        sql, params = _compiled(rows_stmt)
        assert "memories.category_path = %(category_path_1)s" in sql
        assert "memories.category_path LIKE %(category_path_2)s ESCAPE" in sql
        assert params["category_path_1"] == "work%dev"
        assert params["category_path_2"] == f"{escape_like('work%dev')}/%"

    async def test_include_superseded_drops_latest_filter(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_scalar_one_result(0), _scalars_result([])])
        with _patched_memory_session(session):
            await list_memories(USER, include_superseded=True)

        count_stmt, rows_stmt = _executed_stmts(session)
        for stmt in (count_stmt, rows_stmt):
            sql, _ = _compiled(stmt)
            assert "memories.is_latest IS true" not in sql
            assert "memories.is_forgotten IS false" in sql
            assert "memories.forget_after IS NULL OR memories.forget_after >" in sql


# ---------------------------------------------------------------------------
# fts_search
# ---------------------------------------------------------------------------


class TestFtsSearch:
    async def test_returns_records_with_float_scores(self) -> None:
        record_a = make_record()
        record_b = make_record()
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=_all_result([(record_a, "0.75"), (record_b, "0.5")])
        )
        with _patched_memory_session(session):
            hits = await fts_search(USER, "my query", 5)

        assert hits == [(record_a, 0.75), (record_b, 0.5)]
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.search_tsv @@ websearch_to_tsquery" in sql
        assert "ORDER BY ts_rank_cd(memories.search_tsv, websearch_to_tsquery" in sql
        assert "DESC" in sql
        assert "LIMIT" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["websearch_to_tsquery_1"] == "english"
        assert params["websearch_to_tsquery_2"] == "my query"
        assert params["user_id_1"] == USER
        assert params["param_1"] == 5


# ---------------------------------------------------------------------------
# get_memories_for_entities
# ---------------------------------------------------------------------------


class TestGetMemoriesForEntities:
    async def test_empty_entity_ids_returns_empty_without_touching_session(self) -> None:
        session = MagicMock()
        with _patched_memory_session(session) as patched:
            result = await get_memories_for_entities(USER, [], [], 5)

        assert result == []
        patched.assert_not_called()

    async def test_joins_links_orders_by_importance_and_deduplicates(self) -> None:
        entity_a = uuid.uuid4()
        entity_b = uuid.uuid4()
        rows = [make_record()]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result(rows))
        with _patched_memory_session(session):
            got = await get_memories_for_entities(USER, [entity_a, entity_b], [], 3)

        assert got == rows
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "SELECT DISTINCT" in sql
        assert "JOIN memory_entity_links ON memory_entity_links.memory_id = memories.id" in sql
        assert "memory_entity_links.entity_id IN" in sql
        assert "ORDER BY memories.importance DESC, memories.created_at DESC" in sql
        assert "LIMIT" in sql
        assert "memories.user_id = %(user_id_1)s" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["entity_id_1"] == [entity_a, entity_b]
        assert params["user_id_1"] == USER
        assert params["param_1"] == 3

    async def test_excludes_memory_ids(self) -> None:
        exclude_a = uuid.uuid4()
        exclude_b = uuid.uuid4()
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_memories_for_entities(USER, [uuid.uuid4()], [exclude_a, exclude_b], 3)

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.id NOT IN" in sql
        assert params["id_1"] == [exclude_a, exclude_b]

    async def test_filters_by_kinds(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_memories_for_entities(USER, [uuid.uuid4()], [], 3, kinds=["fact"])

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.kind IN" in sql
        assert params["kind_1"] == ["fact"]

    async def test_category_prefix_matches_folder_or_subtree(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_memories_for_entities(USER, [uuid.uuid4()], [], 3, category_prefix="work")

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.category_path = %(category_path_1)s" in sql
        assert "memories.category_path LIKE %(category_path_2)s ESCAPE" in sql
        assert params["category_path_1"] == "work"
        assert params["category_path_2"] == "work/%"


# ---------------------------------------------------------------------------
# get_folder_tree
# ---------------------------------------------------------------------------


class TestGetFolderTree:
    async def test_returns_paths_with_counts_grouped_alphabetically(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([("work", 3), ("work/gaia", 1)]))
        with _patched_memory_session(session):
            tree = await get_folder_tree(USER)

        assert tree == [("work", 3), ("work/gaia", 1)]
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "count(*) AS count_1" in sql
        assert "GROUP BY memories.category_path" in sql
        assert "ORDER BY memories.category_path" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["user_id_1"] == USER


# ---------------------------------------------------------------------------
# get_facts_for_consolidation
# ---------------------------------------------------------------------------


class TestGetFactsForConsolidation:
    async def test_no_filters_returns_newest_first(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_facts_for_consolidation(USER, limit=50)

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "ORDER BY memories.created_at DESC" in sql
        assert "LIMIT" in sql
        assert "memories.shelf_life =" not in sql
        assert "LIKE" not in sql
        assert params["user_id_1"] == USER
        assert params["param_1"] == 50

    async def test_filters_by_shelf_life(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_facts_for_consolidation(USER, shelf_life="durable", limit=10)

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.shelf_life = %(shelf_life_1)s" in sql
        assert params["shelf_life_1"] == "durable"

    async def test_filters_by_category_prefixes(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_facts_for_consolidation(
                USER, category_prefixes=["work", "personal"], limit=10
            )

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.category_path = %(category_path_1)s" in sql
        assert "memories.category_path LIKE %(category_path_2)s ESCAPE" in sql
        assert "memories.category_path = %(category_path_3)s" in sql
        assert "memories.category_path LIKE %(category_path_4)s ESCAPE" in sql
        assert _param_values(params, "category_path") == [
            "work",
            "work/%",
            "personal",
            "personal/%",
        ]

    async def test_empty_prefixes_returns_empty_without_touching_session(self) -> None:
        session = MagicMock()
        with _patched_memory_session(session) as patched:
            result = await get_facts_for_consolidation(USER, category_prefixes=[], limit=10)

        assert result == []
        patched.assert_not_called()

    async def test_shelf_life_and_prefixes_combine_with_and(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_facts_for_consolidation(
                USER, category_prefixes=["work"], shelf_life="durable", limit=10
            )

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.shelf_life = %(shelf_life_1)s" in sql
        assert "memories.category_path = %(category_path_1)s" in sql
        assert "memories.category_path LIKE %(category_path_2)s ESCAPE" in sql
        assert params["shelf_life_1"] == "durable"
        assert params["category_path_1"] == "work"
        assert params["category_path_2"] == "work/%"


# ---------------------------------------------------------------------------
# get_all_live_memories
# ---------------------------------------------------------------------------


class TestGetAllLiveMemories:
    async def test_returns_all_live_ordered_by_folder_then_newest(self) -> None:
        rows = [make_record(), make_record()]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result(rows))
        with _patched_memory_session(session):
            got = await get_all_live_memories(USER)

        assert got == rows
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "ORDER BY memories.category_path, memories.created_at DESC" in sql
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql
        assert params["user_id_1"] == USER


# ---------------------------------------------------------------------------
# get_recent_facts
# ---------------------------------------------------------------------------


class TestGetRecentFacts:
    async def test_returns_contents_newest_first_with_default_limit(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([("fact a",), ("fact b",)]))
        with _patched_memory_session(session):
            facts = await get_recent_facts(USER)

        assert facts == ["fact a", "fact b"]
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "SELECT memories.content" in sql
        assert "ORDER BY memories.created_at DESC" in sql
        assert "LIMIT" in sql
        assert params["param_1"] == 10

    async def test_honors_custom_limit(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([]))
        with _patched_memory_session(session):
            await get_recent_facts(USER, limit=3)

        (stmt,) = _executed_stmts(session)
        _, params = _compiled(stmt)
        assert params["param_1"] == 3


# ---------------------------------------------------------------------------
# get_agenda_memories
# ---------------------------------------------------------------------------


class TestGetAgendaMemories:
    async def test_reads_only_the_agenda_folder_most_important_first(self) -> None:
        # agenda.md is rendered from this query and injected on every turn, so
        # what it drops when it hits the cap has to be the least important item,
        # not an arbitrary row.
        rows = [make_record(), make_record()]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result(rows))
        with _patched_memory_session(session):
            assert await get_agenda_memories(USER, limit=8) == rows

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.category_path = %(category_path_1)s" in sql
        assert params["category_path_1"] == AGENDA_CATEGORY_PATH
        assert "ORDER BY memories.importance DESC, memories.created_at DESC" in sql
        assert params["param_1"] == 8
        assert params["user_id_1"] == USER

    async def test_only_live_rows_reach_the_page(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        with _patched_memory_session(session):
            await get_agenda_memories(USER, limit=8)

        (stmt,) = _executed_stmts(session)
        sql, _ = _compiled(stmt)
        assert "memories.is_latest IS true" in sql
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NULL OR memories.forget_after >" in sql


# ---------------------------------------------------------------------------
# sweep_expired_memories
# ---------------------------------------------------------------------------


class TestSweepExpiredMemories:
    async def test_retires_past_due_rows_and_returns_their_owners(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([("u1",), ("u2",), ("u1",)]))
        session.commit = AsyncMock()
        with _patched_memory_session(session):
            owners = await sweep_expired_memories()

        assert owners == ["u1", "u2", "u1"]
        session.commit.assert_awaited_once()
        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert sql.startswith("UPDATE memories SET")
        assert "is_forgotten=%(is_forgotten)s" in sql
        assert "forget_reason=%(forget_reason)s" in sql
        assert params["is_forgotten"] is True
        assert params["forget_reason"] == "expired"
        assert "RETURNING memories.user_id" in sql

    async def test_the_filter_is_live_rows_whose_expiry_has_arrived(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([]))
        session.commit = AsyncMock()
        with _patched_memory_session(session):
            await sweep_expired_memories()

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.is_forgotten IS false" in sql
        assert "memories.forget_after IS NOT NULL" in sql
        # `<=`, not `<`: an expiry that lands exactly now has arrived.
        assert "memories.forget_after <= %(forget_after_1)s" in sql
        assert params["forget_after_1"].tzinfo is not None

    async def test_an_unscoped_sweep_touches_every_owner(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([]))
        session.commit = AsyncMock()
        with _patched_memory_session(session):
            await sweep_expired_memories()

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        where_clause = sql.split("WHERE", 1)[1].split("RETURNING", 1)[0]
        assert "memories.user_id" not in where_clause
        assert "user_id_1" not in params

    async def test_a_scoped_sweep_is_confined_to_that_owner(self) -> None:
        # The repair script sweeps one user; the nightly task sweeps everyone.
        session = MagicMock()
        session.execute = AsyncMock(return_value=_all_result([]))
        session.commit = AsyncMock()
        with _patched_memory_session(session):
            await sweep_expired_memories(USER)

        (stmt,) = _executed_stmts(session)
        sql, params = _compiled(stmt)
        assert "memories.user_id = %(user_id_1)s" in sql
        assert params["user_id_1"] == USER
