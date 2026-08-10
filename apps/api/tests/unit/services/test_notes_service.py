"""Unit tests for notes service operations.

The service delegates persistence and caching to ``note_repository`` (the
DB/cache behaviour is covered by the repository contract tests). These tests
mock the repository, ChromaDB, and logger seams and assert the service's own
responsibilities: exact delegation arguments, the not-found -> 404 mapping,
the ChromaDB side effects (and their best-effort failure handling), the
wide-event logging, and the shaped ``NoteResponse``.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from langchain_core.documents import Document
import pytest

from app.models.notes_models import NoteDocument, NoteModel, NoteResponse, NoteUpdate
from app.services.notes_service import (
    create_note_service,
    delete_note,
    get_all_notes,
    get_note,
    update_note,
)

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_NOTE_ID = "507f1f77bcf86cd799439099"


def _note_doc(**overrides) -> NoteDocument:
    return NoteDocument.model_validate(
        {
            "id": FAKE_NOTE_ID,
            "user_id": FAKE_USER_ID,
            "content": "<p>Hello</p>",
            "plaintext": "Hello",
            **overrides,
        }
    )


@pytest.fixture
def mock_repo():
    with patch("app.services.notes_service.note_repository") as repo:
        repo.get = AsyncMock()
        repo.list_notes = AsyncMock()
        repo.update = AsyncMock()
        repo.delete = AsyncMock()
        yield repo


@pytest.fixture
def mock_log():
    with patch("app.services.notes_service.log") as mock_log:
        yield mock_log


@pytest.fixture
def mock_chroma():
    with patch(
        "app.services.notes_service.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
    ) as mock_client:
        chroma_instance = AsyncMock()
        mock_client.return_value = chroma_instance
        yield mock_client, chroma_instance


class TestGetNote:
    async def test_returns_note_from_repository(self, mock_repo, mock_log):
        mock_repo.get.return_value = _note_doc(content="<p>Body</p>", plaintext="Body")

        result = await get_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert result == NoteResponse(
            id=FAKE_NOTE_ID,
            content="<p>Body</p>",
            plaintext="Body",
            user_id=FAKE_USER_ID,
        )
        mock_repo.get.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="get_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )

    async def test_raises_404_when_not_found(self, mock_repo, mock_log):
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Note not found"
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="get_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )


class TestGetAllNotes:
    async def test_maps_every_note_to_a_response(self, mock_repo, mock_log):
        mock_repo.list_notes.return_value = [
            _note_doc(id="a", plaintext="A"),
            _note_doc(id="b", plaintext="B"),
        ]

        result = await get_all_notes(FAKE_USER_ID)

        assert result == [
            NoteResponse(id="a", content="<p>Hello</p>", plaintext="A", user_id=FAKE_USER_ID),
            NoteResponse(id="b", content="<p>Hello</p>", plaintext="B", user_id=FAKE_USER_ID),
        ]
        mock_repo.list_notes.assert_awaited_once_with(user_id=FAKE_USER_ID)
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="get_all_notes",
            user_id=FAKE_USER_ID,
        )

    async def test_returns_empty_list(self, mock_repo, mock_log):
        mock_repo.list_notes.return_value = []

        assert await get_all_notes(FAKE_USER_ID) == []
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="get_all_notes",
            user_id=FAKE_USER_ID,
        )


class TestUpdateNote:
    async def test_updates_note_and_syncs_chromadb(self, mock_repo, mock_log, mock_chroma):
        mock_client, chroma_collection = mock_chroma
        mock_repo.update.return_value = _note_doc(content="<p>Updated</p>", plaintext="Updated")

        note = NoteModel(content="<p>Updated</p>", plaintext="Updated")
        result = await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert result == NoteResponse(
            id=FAKE_NOTE_ID,
            content="<p>Updated</p>",
            plaintext="Updated",
            user_id=FAKE_USER_ID,
        )
        mock_repo.update.assert_awaited_once_with(
            FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
            update=NoteUpdate(content="<p>Updated</p>", plaintext="Updated"),
        )
        mock_client.assert_awaited_once_with(collection_name="notes")
        chroma_collection.update_document.assert_called_once_with(
            document_id=FAKE_NOTE_ID, document=Document(page_content="Updated")
        )
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="update_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )
        mock_log.info.assert_called_once_with(
            "Note with id updated in ChromaDB", note_id=FAKE_NOTE_ID
        )

    async def test_raises_404_when_note_not_matched(self, mock_repo, mock_log):
        mock_repo.update.return_value = None

        note = NoteModel(content="<p>New</p>", plaintext="New")
        with pytest.raises(HTTPException) as exc_info:
            await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Note not found"
        mock_repo.update.assert_awaited_once_with(
            FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
            update=NoteUpdate(content="<p>New</p>", plaintext="New"),
        )
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="update_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )

    async def test_chromadb_error_does_not_fail_update(self, mock_repo, mock_log):
        mock_repo.update.return_value = _note_doc()

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            note = NoteModel(content="<p>Changed</p>", plaintext="Changed")
            result = await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert result == NoteResponse(
            id=FAKE_NOTE_ID,
            content="<p>Hello</p>",
            plaintext="Hello",
            user_id=FAKE_USER_ID,
        )
        mock_log.error.assert_called_once_with(
            "Failed to update note in ChromaDB",
            error="ChromaDB down",
            error_type="Exception",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )
        mock_log.info.assert_not_called()


class TestDeleteNote:
    async def test_deletes_note_and_chromadb_entry(self, mock_repo, mock_log, mock_chroma):
        mock_client, chroma_collection = mock_chroma
        mock_repo.delete.return_value = True

        await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)

        mock_repo.delete.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)
        mock_client.assert_awaited_once_with(collection_name="notes")
        chroma_collection.adelete.assert_called_once_with(ids=[FAKE_NOTE_ID])
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="delete_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )
        mock_log.info.assert_called_once_with(
            "Note with id deleted from ChromaDB", note_id=FAKE_NOTE_ID
        )

    async def test_raises_404_when_not_found(self, mock_repo, mock_log):
        mock_repo.delete.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Note not found"
        mock_repo.delete.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)
        mock_log.set.assert_called_once_with(
            component="notes_service",
            operation="delete_note",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )

    async def test_chromadb_error_does_not_fail_deletion(self, mock_repo, mock_log):
        mock_repo.delete.return_value = True

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)  # must not raise

        mock_repo.delete.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)
        mock_log.error.assert_called_once_with(
            "Failed to delete note from ChromaDB",
            error="ChromaDB down",
            error_type="Exception",
            note_id=FAKE_NOTE_ID,
            user_id=FAKE_USER_ID,
        )
        mock_log.info.assert_not_called()


class TestCreateNoteService:
    async def test_creates_note_via_insert_note(self):
        expected = NoteResponse(
            id="abc123", content="<p>Hi</p>", plaintext="Hi", user_id=FAKE_USER_ID
        )
        note = NoteModel(content="<p>Hi</p>", plaintext="Hi")
        with patch(
            "app.services.notes_service.insert_note",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_insert:
            result = await create_note_service(note, FAKE_USER_ID)

        assert result == expected
        mock_insert.assert_awaited_once_with(note, FAKE_USER_ID)

    async def test_raises_500_on_insert_failure(self, mock_log):
        note = NoteModel(content="<p>Bad</p>", plaintext="Bad")
        with patch(
            "app.services.notes_service.insert_note",
            new_callable=AsyncMock,
            side_effect=Exception("insert failed"),
        ) as mock_insert:
            with pytest.raises(HTTPException) as exc_info:
                await create_note_service(note, FAKE_USER_ID)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create note"
        mock_insert.assert_awaited_once_with(note, FAKE_USER_ID)
        mock_log.error.assert_called_once_with(
            "Failed to create note",
            error="insert failed",
            error_type="Exception",
            user_id=FAKE_USER_ID,
        )
