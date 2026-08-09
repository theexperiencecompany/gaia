"""Unit tests for app.memory.pg_store.documents — core markdown document CRUD.

The ``memory_session`` seam is mocked; the SQL statements built, the
MemoryDocument mutations applied, and the values returned are real.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.memory import DOCUMENT_HISTORY_LIMIT, MemoryDocType
from app.memory.pg_store.documents import get_document, get_documents, upsert_document
from app.models.memory_db_models import MemoryDocument

USER_ID = "user-123"

FIXED_NOW = datetime(2026, 8, 9, 12, 34, 56, tzinfo=UTC)


class _FixedClock:
    """Stand-in for the module's ``datetime`` with a deterministic ``now``."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return FIXED_NOW


def make_document(
    *,
    doc_type: str = MemoryDocType.USER_MD.value,
    content: str = "initial",
    version: int = 1,
    history: list[dict[str, Any]] | None = None,
) -> MemoryDocument:
    """A detached MemoryDocument — no session, no DB."""
    document = MemoryDocument(user_id=USER_ID, doc_type=doc_type, content=content)
    document.version = version
    document.history = history if history is not None else []
    return document


def session_cm(session: AsyncMock) -> AsyncMock:
    """The async context manager ``memory_session`` should return when patched."""
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    return cm


def bound_params(stmt: Any) -> set[Any]:
    """The values bound to a SQL statement's parameters."""
    return set(stmt.compile().params.values())


# ---------------------------------------------------------------------------
# get_documents
# ---------------------------------------------------------------------------


class TestGetDocuments:
    """Tests for get_documents()."""

    async def test_returns_all_user_documents_ordered_by_type(self) -> None:
        """Should return every document for the user, ordered by doc_type."""
        user_doc = make_document(doc_type=MemoryDocType.USER_MD.value, content="user")
        agenda_doc = make_document(doc_type=MemoryDocType.AGENDA_MD.value, content="agenda")
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [user_doc, agenda_doc]
        session.execute.return_value = result

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            docs = await get_documents(USER_ID)

        assert docs == [user_doc, agenda_doc]
        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        assert bound_params(stmt) == {USER_ID}
        assert "ORDER BY memory_documents.doc_type" in str(stmt)

    async def test_returns_empty_list_when_user_has_no_documents(self) -> None:
        """Should return [] when the user has no core documents."""
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            docs = await get_documents(USER_ID)

        assert docs == []

    async def test_propagates_database_errors(self) -> None:
        """A DB failure must propagate, not be swallowed."""
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("db down")

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await get_documents(USER_ID)


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


class TestGetDocument:
    """Tests for get_document()."""

    async def test_returns_document_for_user_and_type(self) -> None:
        """Should return the matching document, filtering by user and doc type value."""
        document = make_document(content="current")
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = document
        session.execute.return_value = result

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            found = await get_document(USER_ID, MemoryDocType.USER_MD)

        assert found is document
        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        assert bound_params(stmt) == {USER_ID, MemoryDocType.USER_MD.value}

    async def test_returns_none_when_document_missing(self) -> None:
        """Should return None when no document exists for the user and type."""
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            found = await get_document(USER_ID, MemoryDocType.AGENDA_MD)

        assert found is None

    async def test_propagates_database_errors(self) -> None:
        """A DB failure must propagate, not be swallowed."""
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("db down")

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await get_document(USER_ID, MemoryDocType.USER_MD)


# ---------------------------------------------------------------------------
# upsert_document
# ---------------------------------------------------------------------------


class TestUpsertDocument:
    """Tests for upsert_document()."""

    async def test_creates_new_document_when_none_exists(self) -> None:
        """Should insert a new document without archiving anything."""
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            created = await upsert_document(USER_ID, MemoryDocType.USER_MD, "# Hello")

        assert isinstance(created, MemoryDocument)
        assert created.user_id == USER_ID
        assert created.doc_type == MemoryDocType.USER_MD.value
        assert created.content == "# Hello"
        session.add.assert_called_once_with(created)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(created)

    async def test_updates_existing_document_archiving_previous_version(self) -> None:
        """Should bump version, archive the outgoing content, and refresh."""
        old_history = [
            {"version": 2, "content": "v2", "updated_at": "2026-01-02T00:00:00+00:00"},
            {"version": 1, "content": "v1", "updated_at": "2026-01-01T00:00:00+00:00"},
        ]
        document = make_document(content="v3", version=3, history=old_history)
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = document
        session.execute.return_value = result

        with (
            patch(
                "app.memory.pg_store.documents.memory_session",
                return_value=session_cm(session),
            ),
            patch("app.memory.pg_store.documents.datetime", _FixedClock),
        ):
            result = await upsert_document(USER_ID, MemoryDocType.USER_MD, "v4")

        assert result is document
        assert document.version == 4
        assert document.content == "v4"
        assert document.history == [
            {"version": 3, "content": "v3", "updated_at": FIXED_NOW.isoformat()},
            *old_history,
        ]
        session.add.assert_not_called()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(document)

    async def test_caps_history_at_document_history_limit(self) -> None:
        """Should keep only DOCUMENT_HISTORY_LIMIT entries, newest first."""
        old_history = [
            {
                "version": DOCUMENT_HISTORY_LIMIT + 1 - i,
                "content": f"v{DOCUMENT_HISTORY_LIMIT + 1 - i}",
                "updated_at": f"2026-01-{i:02d}T00:00:00+00:00",
            }
            for i in range(1, DOCUMENT_HISTORY_LIMIT + 1)
        ]
        document = make_document(
            content=f"v{DOCUMENT_HISTORY_LIMIT + 1}",
            version=DOCUMENT_HISTORY_LIMIT + 1,
            history=old_history,
        )
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = document
        session.execute.return_value = result

        with (
            patch(
                "app.memory.pg_store.documents.memory_session",
                return_value=session_cm(session),
            ),
            patch("app.memory.pg_store.documents.datetime", _FixedClock),
        ):
            result = await upsert_document(
                USER_ID, MemoryDocType.USER_MD, f"v{DOCUMENT_HISTORY_LIMIT + 2}"
            )

        assert result is document
        assert len(document.history) == DOCUMENT_HISTORY_LIMIT
        assert document.history[0] == {
            "version": DOCUMENT_HISTORY_LIMIT + 1,
            "content": f"v{DOCUMENT_HISTORY_LIMIT + 1}",
            "updated_at": FIXED_NOW.isoformat(),
        }
        assert document.history[-1]["version"] == 2
        assert all(entry["version"] != 1 for entry in document.history)

    async def test_propagates_commit_failure(self) -> None:
        """A commit failure must propagate; refresh must not run."""
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result
        session.commit.side_effect = RuntimeError("db down")

        with patch(
            "app.memory.pg_store.documents.memory_session",
            return_value=session_cm(session),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await upsert_document(USER_ID, MemoryDocType.USER_MD, "# Hello")

        session.refresh.assert_not_awaited()
