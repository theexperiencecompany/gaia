"""Unit tests for app.memory.pg_store.vectors — the hosted-model vectors table.

memory_session is mocked (hermetic); each statement is compiled against the
Postgres dialect and compared whole, so scoping, liveness, the change window
and the upsert's conflict target are pinned. The real round trip is covered by
tests/integration/real/memory/test_fast_recall.py.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import numpy as np
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from app.memory.pg_store import vectors
from app.memory.pg_store.vectors import (
    live_memories_without_vector,
    live_vectors,
    pack,
    upsert_vectors,
    vectors_changed_since,
)

USER = "u1"
MODEL = "text-embedding-3-small"
READ_AT = datetime(2026, 11, 17, tzinfo=UTC)
SINCE = datetime(2026, 11, 16, tzinfo=UTC)


def _session(rows: list[tuple[Any, ...]]) -> MagicMock:
    """Build a session whose first execute returns READ_AT and the next returns rows."""
    now, result = MagicMock(), MagicMock()
    now.scalar_one.return_value = READ_AT
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[now, result])
    session.commit = AsyncMock()
    return session


@contextmanager
def _patched_session(session: MagicMock) -> Iterator[None]:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    with patch.object(vectors, "memory_session", return_value=ctx):
        yield


def _compiled(statement: ClauseElement) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), dict(compiled.params)


def _statements(session: MagicMock) -> list[tuple[str, dict[str, Any]]]:
    return [_compiled(call.args[0]) for call in session.execute.await_args_list]


def _blob(*values: float) -> bytes:
    return np.asarray(values, dtype="<f4").tobytes()


def test_pack_stores_the_unit_vector_as_little_endian_float32() -> None:
    assert pack([3.0, 4.0]) == _blob(0.6, 0.8)


async def test_upsert_replaces_the_vector_for_the_same_memory_and_model() -> None:
    memory_id = uuid.UUID(int=1)
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    with _patched_session(session):
        await upsert_vectors(USER, MODEL, [(memory_id, [3.0, 4.0])])

    ((sql, params),) = _statements(session)
    assert sql == (
        "INSERT INTO memory_vectors (memory_id, model, user_id, vector, created_at, updated_at) "
        "VALUES (%(memory_id_m0)s::UUID, %(model_m0)s, %(user_id_m0)s, %(vector_m0)s, now(), "
        "now()) ON CONFLICT (memory_id, model) DO UPDATE SET vector = excluded.vector, "
        "updated_at = now()"
    )
    assert params == {
        "memory_id_m0": memory_id,
        "model_m0": MODEL,
        "user_id_m0": USER,
        "vector_m0": _blob(0.6, 0.8),
    }
    session.commit.assert_awaited_once()


async def test_upserting_nothing_opens_no_session() -> None:
    with patch.object(vectors, "memory_session") as opened:
        await upsert_vectors(USER, MODEL, [])

    opened.assert_not_called()


async def test_live_vectors_reads_the_users_live_set_under_the_model() -> None:
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    session = _session([(first, _blob(1, 0)), (second, _blob(0, 1))])
    with _patched_session(session):
        snapshot = await live_vectors(USER, MODEL)

    assert snapshot.ids == [str(first), str(second)]
    assert snapshot.matrix.dtype == np.float32
    assert snapshot.matrix.tolist() == [[1.0, 0.0], [0.0, 1.0]]
    assert snapshot.read_at == READ_AT
    (now_sql, _), (sql, params) = _statements(session)
    assert now_sql == "SELECT now() AS now_1"
    assert sql == (
        "SELECT memory_vectors.memory_id, memory_vectors.vector FROM memory_vectors "
        "JOIN memories ON memories.id = memory_vectors.memory_id "
        "WHERE memory_vectors.user_id = %(user_id_1)s AND memory_vectors.model = %(model_1)s "
        "AND memories.is_latest IS true AND memories.is_forgotten IS false AND "
        "(memories.forget_after IS NULL OR memories.forget_after > %(forget_after_1)s)"
    )
    assert (params["user_id_1"], params["model_1"]) == (USER, MODEL)


async def test_a_user_without_vectors_holds_an_empty_float32_matrix() -> None:
    with _patched_session(_session([])):
        snapshot = await live_vectors(USER, MODEL)

    assert snapshot.ids == []
    assert snapshot.matrix.shape == (0, 0)
    assert snapshot.matrix.dtype == np.float32


async def test_changes_since_split_into_live_vectors_and_ids_no_longer_live() -> None:
    live, dead = uuid.UUID(int=1), uuid.UUID(int=2)
    session = _session([(live, _blob(1, 0), True), (dead, _blob(0, 1), False)])
    with _patched_session(session):
        delta = await vectors_changed_since(USER, MODEL, SINCE)

    assert delta.live_ids == [str(live)]
    assert delta.matrix.tolist() == [[1.0, 0.0]]
    assert delta.dead_ids == [str(dead)]
    assert delta.read_at == READ_AT
    (now_sql, _), (sql, params) = _statements(session)
    assert now_sql == "SELECT now() AS now_1"
    assert sql == (
        "SELECT memory_vectors.memory_id, memory_vectors.vector, "
        "memories.is_latest IS true AND memories.is_forgotten IS false AND "
        "(memories.forget_after IS NULL OR memories.forget_after > %(forget_after_1)s) AS anon_1 "
        "FROM memory_vectors JOIN memories ON memories.id = memory_vectors.memory_id "
        "WHERE memory_vectors.user_id = %(user_id_1)s AND memory_vectors.model = %(model_1)s "
        "AND (memory_vectors.updated_at > %(updated_at_1)s "
        "OR memories.updated_at > %(updated_at_2)s)"
    )
    assert (params["user_id_1"], params["model_1"]) == (USER, MODEL)
    assert params["updated_at_1"] == params["updated_at_2"] == SINCE


async def test_the_backfill_cursor_pages_live_memories_missing_a_vector_by_id() -> None:
    after = uuid.UUID(int=5)
    record = MagicMock()
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [record]
    session.execute = AsyncMock(return_value=result)
    with _patched_session(session):
        assert await live_memories_without_vector(MODEL, after, 10) == [record]

    ((sql, params),) = _statements(session)
    assert sql.startswith("SELECT memories.id, memories.user_id")
    assert sql.endswith(
        "WHERE memories.is_latest IS true AND memories.is_forgotten IS false "
        "AND NOT (EXISTS (SELECT memory_vectors.memory_id FROM memory_vectors "
        "WHERE memory_vectors.memory_id = memories.id AND memory_vectors.model = %(model_1)s)) "
        "AND memories.id > %(id_1)s::UUID ORDER BY memories.id LIMIT %(param_1)s"
    )
    assert params == {"model_1": MODEL, "id_1": after, "param_1": 10}


async def test_the_first_backfill_page_starts_from_the_lowest_id() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    with _patched_session(session):
        await live_memories_without_vector(MODEL, None, 10)

    ((sql, _),) = _statements(session)
    assert "memories.id >" not in sql
