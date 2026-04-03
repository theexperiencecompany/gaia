"""Unit tests for notes service operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.models.notes_models import NoteModel, NoteResponse
from app.services.notes_service import (
    create_note_service,
    delete_note,
    fetch_notes,
    get_all_notes,
    get_note,
    update_note,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_notes_collection():
    with patch("app.services.notes_service.notes_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_redis():
    with (
        patch("app.services.notes_service.get_cache", new_callable=AsyncMock) as m_get,
        patch("app.services.notes_service.set_cache", new_callable=AsyncMock) as m_set,
        patch(
            "app.services.notes_service.delete_cache", new_callable=AsyncMock
        ) as m_del,
    ):
        yield m_get, m_set, m_del


@pytest.fixture
def mock_chroma():
    with patch(
        "app.services.notes_service.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
    ) as mock_client:
        chroma_instance = AsyncMock()
        mock_client.return_value = chroma_instance
        yield chroma_instance


@pytest.fixture
def sample_note_oid():
    return ObjectId()


@pytest.fixture
def sample_note_doc(sample_note_oid):
    return {
        "_id": sample_note_oid,
        "content": "<p>Hello</p>",
        "plaintext": "Hello",
        "user_id": FAKE_USER_ID,
        "auto_created": False,
        "title": "My Note",
        "description": "A test note",
    }


@pytest.fixture
def sample_note_model():
    return NoteModel(content="<p>Hello</p>", plaintext="Hello")


# ---------------------------------------------------------------------------
# get_note
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNote:
    async def test_returns_cached_note(
        self, mock_notes_collection, mock_redis, sample_note_oid
    ):
        m_get, _m_set, _m_del = mock_redis
        cached_data = {
            "id": str(sample_note_oid),
            "content": "<p>Hello</p>",
            "plaintext": "Hello",
            "user_id": FAKE_USER_ID,
        }
        m_get.return_value = cached_data

        result = await get_note(str(sample_note_oid), FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        assert result.id == str(sample_note_oid)
        mock_notes_collection.find_one.assert_not_called()

    async def test_returns_note_from_db_and_caches(
        self, mock_notes_collection, mock_redis, sample_note_doc, sample_note_oid
    ):
        m_get, m_set, _m_del = mock_redis
        m_get.return_value = None
        mock_notes_collection.find_one = AsyncMock(return_value=sample_note_doc)

        result = await get_note(str(sample_note_oid), FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        assert result.content == "<p>Hello</p>"
        m_set.assert_called_once()

    async def test_raises_404_when_not_found(
        self, mock_notes_collection, mock_redis, sample_note_oid
    ):
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = None
        mock_notes_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_note(str(sample_note_oid), FAKE_USER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Note not found"


# ---------------------------------------------------------------------------
# get_all_notes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllNotes:
    async def test_returns_cached_notes(self, mock_notes_collection, mock_redis):
        m_get, _m_set, _m_del = mock_redis
        cached = {
            "notes": [
                {
                    "id": "abc123",
                    "content": "<p>C</p>",
                    "plaintext": "C",
                    "user_id": FAKE_USER_ID,
                }
            ]
        }
        m_get.return_value = cached

        result = await get_all_notes(FAKE_USER_ID)

        assert len(result) == 1
        assert isinstance(result[0], NoteResponse)
        mock_notes_collection.find.assert_not_called()

    async def test_returns_notes_from_db_and_caches(
        self, mock_notes_collection, mock_redis
    ):
        m_get, m_set, _m_del = mock_redis
        m_get.return_value = None

        oid = ObjectId()
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": oid,
                    "content": "<p>DB</p>",
                    "plaintext": "DB",
                    "user_id": FAKE_USER_ID,
                }
            ]
        )
        mock_notes_collection.find.return_value = cursor

        result = await get_all_notes(FAKE_USER_ID)

        assert len(result) == 1
        assert result[0].plaintext == "DB"
        m_set.assert_called_once()

    async def test_returns_empty_list_when_no_notes(
        self, mock_notes_collection, mock_redis
    ):
        m_get, m_set, _m_del = mock_redis
        m_get.return_value = None

        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.find.return_value = cursor

        result = await get_all_notes(FAKE_USER_ID)

        assert result == []

    async def test_skips_cache_when_notes_key_missing(
        self, mock_notes_collection, mock_redis
    ):
        """When cache returns a dict but without 'notes' key, fall through to DB."""
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = {"other_key": "value"}

        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.find.return_value = cursor

        result = await get_all_notes(FAKE_USER_ID)

        assert result == []
        mock_notes_collection.find.assert_called_once()


# ---------------------------------------------------------------------------
# update_note
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateNote:
    async def test_updates_note_and_invalidates_cache(
        self,
        mock_notes_collection,
        mock_redis,
        mock_chroma,
        sample_note_doc,
        sample_note_oid,
    ):
        _m_get, m_set, m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)
        mock_notes_collection.find_one = AsyncMock(return_value=sample_note_doc)

        note = NoteModel(content="<p>Updated</p>", plaintext="Updated")
        result = await update_note(str(sample_note_oid), note, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        assert m_del.call_count == 2  # note cache + notes list cache
        m_set.assert_called_once()

    async def test_raises_404_when_note_not_matched(
        self, mock_notes_collection, mock_redis, sample_note_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=0)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)

        note = NoteModel(content="<p>New</p>", plaintext="New")

        with pytest.raises(HTTPException) as exc_info:
            await update_note(str(sample_note_oid), note, FAKE_USER_ID)

        assert exc_info.value.status_code == 404

    async def test_raises_value_error_when_refetch_fails(
        self,
        mock_notes_collection,
        mock_redis,
        sample_note_oid,
    ):
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)
        mock_notes_collection.find_one = AsyncMock(return_value=None)

        note = NoteModel(content="<p>X</p>", plaintext="X")

        with pytest.raises(ValueError, match="not found after update"):
            await update_note(str(sample_note_oid), note, FAKE_USER_ID)

    async def test_updates_chromadb_when_plaintext_changes(
        self,
        mock_notes_collection,
        mock_redis,
        mock_chroma,
        sample_note_doc,
        sample_note_oid,
    ):
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)
        mock_notes_collection.find_one = AsyncMock(return_value=sample_note_doc)

        note = NoteModel(content="<p>Changed</p>", plaintext="Changed")
        await update_note(str(sample_note_oid), note, FAKE_USER_ID)

        mock_chroma.update_document.assert_called_once()

    async def test_chromadb_error_does_not_fail_update(
        self,
        mock_notes_collection,
        mock_redis,
        sample_note_doc,
        sample_note_oid,
    ):
        """ChromaDB failure should be logged but not block the update."""
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)
        mock_notes_collection.find_one = AsyncMock(return_value=sample_note_doc)

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            note = NoteModel(content="<p>Changed</p>", plaintext="Changed")
            result = await update_note(str(sample_note_oid), note, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)

    async def test_chromadb_called_when_plaintext_present(
        self,
        mock_notes_collection,
        mock_redis,
        mock_chroma,
        sample_note_oid,
    ):
        """NoteModel always includes plaintext, so ChromaDB is always updated."""
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_notes_collection.update_one = AsyncMock(return_value=update_result)
        doc = {
            "_id": sample_note_oid,
            "content": "<p>Updated</p>",
            "plaintext": "Updated",
            "user_id": FAKE_USER_ID,
        }
        mock_notes_collection.find_one = AsyncMock(return_value=doc)

        note = NoteModel(content="<p>Updated</p>", plaintext="Updated")
        result = await update_note(str(sample_note_oid), note, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        mock_chroma.update_document.assert_called_once()


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteNote:
    async def test_deletes_note_and_invalidates_cache(
        self, mock_notes_collection, mock_redis, mock_chroma, sample_note_oid
    ):
        _m_get, _m_set, m_del = mock_redis
        delete_result = MagicMock(deleted_count=1)
        mock_notes_collection.delete_one = AsyncMock(return_value=delete_result)

        await delete_note(str(sample_note_oid), FAKE_USER_ID)

        assert m_del.call_count == 2
        mock_chroma.adelete.assert_called_once_with(ids=[str(sample_note_oid)])

    async def test_raises_404_when_not_found(
        self, mock_notes_collection, mock_redis, sample_note_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        delete_result = MagicMock(deleted_count=0)
        mock_notes_collection.delete_one = AsyncMock(return_value=delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_note(str(sample_note_oid), FAKE_USER_ID)

        assert exc_info.value.status_code == 404

    async def test_chromadb_error_does_not_fail_deletion(
        self, mock_notes_collection, mock_redis, sample_note_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        delete_result = MagicMock(deleted_count=1)
        mock_notes_collection.delete_one = AsyncMock(return_value=delete_result)

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            await delete_note(str(sample_note_oid), FAKE_USER_ID)

        # No exception raised -- ChromaDB error is swallowed


# ---------------------------------------------------------------------------
# create_note_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateNoteService:
    async def test_creates_note_via_insert_note(self):
        expected = NoteResponse(
            id="abc123",
            content="<p>Hi</p>",
            plaintext="Hi",
            user_id=FAKE_USER_ID,
        )
        with patch(
            "app.services.notes_service.insert_note",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            note = NoteModel(content="<p>Hi</p>", plaintext="Hi")
            result = await create_note_service(note, FAKE_USER_ID)

        assert result.id == "abc123"

    async def test_raises_500_on_insert_failure(self):
        with patch(
            "app.services.notes_service.insert_note",
            new_callable=AsyncMock,
            side_effect=Exception("insert failed"),
        ):
            note = NoteModel(content="<p>Bad</p>", plaintext="Bad")

            with pytest.raises(HTTPException) as exc_info:
                await create_note_service(note, FAKE_USER_ID)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Failed to create note"


# ---------------------------------------------------------------------------
# fetch_notes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchNotes:
    async def test_appends_notes_to_context_when_found(self):
        context = {
            "last_message": {"content": "What are my notes?"},
            "query_text": "my notes",
            "user": {"user_id": FAKE_USER_ID},
        }
        mock_notes = [
            {"title": "Note 1", "content": "Content 1"},
            {"title": "Note 2", "content": "Content 2"},
        ]
        with patch(
            "app.services.notes_service.search_notes_by_similarity",
            new_callable=AsyncMock,
            return_value=mock_notes,
        ):
            result = await fetch_notes(context)

        assert result["notes_added"] is True
        assert "Note 1" in result["last_message"]["content"]
        assert "Note 2" in result["last_message"]["content"]

    async def test_marks_notes_not_added_when_empty(self):
        context = {
            "last_message": {"content": "Hello"},
            "query_text": "hello",
            "user": {"user_id": FAKE_USER_ID},
        }
        with patch(
            "app.services.notes_service.search_notes_by_similarity",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await fetch_notes(context)

        assert result["notes_added"] is False

    async def test_handles_notes_without_title(self):
        context = {
            "last_message": {"content": "Check notes"},
            "query_text": "notes",
            "user": {"user_id": FAKE_USER_ID},
        }
        mock_notes = [{"content": "No title here"}]
        with patch(
            "app.services.notes_service.search_notes_by_similarity",
            new_callable=AsyncMock,
            return_value=mock_notes,
        ):
            result = await fetch_notes(context)

        assert result["notes_added"] is True
        assert "Untitled Note" in result["last_message"]["content"]

    async def test_handles_notes_without_content(self):
        context = {
            "last_message": {"content": "Check notes"},
            "query_text": "notes",
            "user": {"user_id": FAKE_USER_ID},
        }
        mock_notes = [{"title": "Empty Note"}]
        with patch(
            "app.services.notes_service.search_notes_by_similarity",
            new_callable=AsyncMock,
            return_value=mock_notes,
        ):
            result = await fetch_notes(context)

        assert result["notes_added"] is True
