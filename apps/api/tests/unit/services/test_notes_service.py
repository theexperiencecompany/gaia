"""Unit tests for notes service operations.

The service now delegates all persistence and caching to ``note_repository`` (the
DB/cache behaviour is covered by the repository contract tests). These tests mock
the repository singleton and assert the service's own responsibilities: delegating
correctly, mapping the not-found case to 404, orchestrating the ChromaDB side
effects, and shaping the ``NoteResponse``.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.constants.chroma import CHROMA_NOTES_COLLECTION
from app.models.notes_models import NoteDocument, NoteModel, NoteResponse
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
def mock_chroma():
    """The patched collection lookup; ``.return_value`` is the collection it hands back.

    Yielding the lookup rather than the collection is what lets a test pin WHICH
    collection the service opens. That matters because the name carries the
    ``GAIA_CHROMA_COLLECTION_SUFFIX`` lane namespace — a service that opened a
    hardcoded ``"notes"`` would read and write a different collection from the
    one the app indexes into, and every assertion about "it called Chroma"
    would still pass.
    """
    with patch(
        "app.services.notes_service.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
    ) as mock_client:
        mock_client.return_value = AsyncMock()
        yield mock_client


@pytest.fixture
def sample_note_model():
    return NoteModel(content="<p>Hello</p>", plaintext="Hello")


class TestGetNote:
    async def test_returns_note_from_repository(self, mock_repo):
        mock_repo.get.return_value = _note_doc(content="<p>Body</p>", plaintext="Body")

        result = await get_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        assert result.id == FAKE_NOTE_ID
        assert result.content == "<p>Body</p>"
        mock_repo.get.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)

    async def test_raises_404_when_not_found(self, mock_repo):
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Note not found"


class TestGetAllNotes:
    async def test_maps_every_note_to_a_response(self, mock_repo):
        mock_repo.list_notes.return_value = [
            _note_doc(id="a", plaintext="A"),
            _note_doc(id="b", plaintext="B"),
        ]

        result = await get_all_notes(FAKE_USER_ID)

        assert [n.plaintext for n in result] == ["A", "B"]
        assert all(isinstance(n, NoteResponse) for n in result)
        mock_repo.list_notes.assert_awaited_once_with(user_id=FAKE_USER_ID)

    async def test_returns_empty_list(self, mock_repo):
        mock_repo.list_notes.return_value = []
        assert await get_all_notes(FAKE_USER_ID) == []


class TestUpdateNote:
    async def test_updates_note_and_syncs_chromadb(self, mock_repo, mock_chroma):
        mock_repo.update.return_value = _note_doc(content="<p>Updated</p>", plaintext="Updated")

        note = NoteModel(content="<p>Updated</p>", plaintext="Updated")
        result = await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)
        assert result.plaintext == "Updated"
        mock_repo.update.assert_awaited_once()
        mock_chroma.assert_awaited_once_with(collection_name=CHROMA_NOTES_COLLECTION)
        mock_chroma.return_value.update_document.assert_called_once()

    async def test_raises_404_when_note_not_matched(self, mock_repo):
        mock_repo.update.return_value = None

        note = NoteModel(content="<p>New</p>", plaintext="New")
        with pytest.raises(HTTPException) as exc_info:
            await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert exc_info.value.status_code == 404

    async def test_chromadb_error_does_not_fail_update(self, mock_repo):
        mock_repo.update.return_value = _note_doc()

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            note = NoteModel(content="<p>Changed</p>", plaintext="Changed")
            result = await update_note(FAKE_NOTE_ID, note, FAKE_USER_ID)

        assert isinstance(result, NoteResponse)


class TestDeleteNote:
    async def test_deletes_note_and_chromadb_entry(self, mock_repo, mock_chroma):
        mock_repo.delete.return_value = True

        await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)

        mock_repo.delete.assert_awaited_once_with(FAKE_NOTE_ID, user_id=FAKE_USER_ID)
        mock_chroma.assert_awaited_once_with(collection_name=CHROMA_NOTES_COLLECTION)
        mock_chroma.return_value.adelete.assert_called_once_with(ids=[FAKE_NOTE_ID])

    async def test_raises_404_when_not_found(self, mock_repo):
        mock_repo.delete.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)

        assert exc_info.value.status_code == 404

    async def test_chromadb_error_does_not_fail_deletion(self, mock_repo):
        mock_repo.delete.return_value = True

        with patch(
            "app.services.notes_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            await delete_note(FAKE_NOTE_ID, FAKE_USER_ID)  # must not raise


class TestCreateNoteService:
    async def test_creates_note_via_insert_note(self):
        expected = NoteResponse(
            id="abc123", content="<p>Hi</p>", plaintext="Hi", user_id=FAKE_USER_ID
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
