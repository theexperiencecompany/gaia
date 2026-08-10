"""Unit tests for notes API endpoints.

Tests the notes CRUD endpoints with mocked service layer to verify routing,
status codes, response bodies, service-call args, and validation.

Each endpoint wraps the service call in ``try/except``: a service-raised
``HTTPException`` (e.g. the service's 404 "Note not found") passes through
unchanged, while any other exception becomes a 500 with the endpoint's own
detail. The module's wide-event logger is a mocked seam so the observability
contract (``log.set`` on success, ``log.error`` on failure) is asserted too —
a wide event with the wrong operation/outcome is a broken alert path, not a
style nit.

With ``ASGITransport(raise_app_exceptions=False)`` (the client fixture),
service errors surface as HTTP responses through FastAPI's exception handler.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
from httpx import AsyncClient
import pytest

from app.constants.log_tags import LogTag
from app.models.notes_models import NoteModel

NOTES_BASE = "/api/v1/notes"
USER_ID = "507f1f77bcf86cd799439011"

FAKE_NOTE_RESPONSE = {
    "id": "note-001",
    "content": "<p>Test note</p>",
    "plaintext": "Test note",
    "auto_created": False,
    "user_id": "507f1f77bcf86cd799439011",
    "title": None,
    "description": None,
}

FAKE_NOTE_PAYLOAD = {"content": "<p>Test note</p>", "plaintext": "Test note"}

UPDATED_NOTE_PAYLOAD = {"content": "<p>Updated</p>", "plaintext": "Updated"}


@pytest.fixture
def mock_log() -> Iterator[MagicMock]:
    """The endpoint module's wide-event logger, patched so calls are assertable."""
    with patch("app.api.v1.endpoints.notes.log") as m:
        yield m


class TestCreateNote:
    """POST /api/v1/notes"""

    @patch(
        "app.api.v1.endpoints.notes.create_note_service",
        new_callable=AsyncMock,
    )
    async def test_create_note_returns_201(
        self, mock_create: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_create.return_value = FAKE_NOTE_RESPONSE
        response = await client.post(NOTES_BASE, json=FAKE_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == FAKE_NOTE_RESPONSE
        mock_create.assert_awaited_once_with(NoteModel(**FAKE_NOTE_PAYLOAD), USER_ID)
        mock_log.set.assert_any_call(operation="create_note")
        mock_log.set.assert_any_call(outcome="success")

    @patch(
        "app.api.v1.endpoints.notes.create_note_service",
        new_callable=AsyncMock,
    )
    async def test_create_note_passthrough_service_httpexception(
        self, mock_create: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        """A deliberate HTTPException from the service is not masked as a 500."""
        mock_create.side_effect = HTTPException(
            status_code=status.HTTP_418_IM_A_TEAPOT, detail="custom"
        )
        response = await client.post(NOTES_BASE, json=FAKE_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_418_IM_A_TEAPOT
        assert response.json() == {"detail": "custom"}
        mock_log.set.assert_called_once_with(operation="create_note")
        mock_log.error.assert_not_called()

    async def test_create_note_missing_content_returns_422(self, client: AsyncClient):
        response = await client.post(NOTES_BASE, json={"plaintext": "Test"})
        assert response.status_code == 422

    async def test_create_note_missing_plaintext_returns_422(self, client: AsyncClient):
        response = await client.post(NOTES_BASE, json={"content": "<p>Test</p>"})
        assert response.status_code == 422

    async def test_create_note_empty_body_returns_422(self, client: AsyncClient):
        response = await client.post(NOTES_BASE, json={})
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.notes.create_note_service",
        new_callable=AsyncMock,
    )
    async def test_create_note_service_error_returns_500(
        self, mock_create: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_create.side_effect = Exception("DB write failed")
        response = await client.post(NOTES_BASE, json=FAKE_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"detail": "Failed to create note"}
        mock_log.set.assert_called_once_with(operation="create_note")
        mock_log.error.assert_called_once_with(
            f"{LogTag.API} Error creating note",
            user_id=USER_ID,
            error_type="Exception",
            error="DB write failed",
        )


class TestGetNote:
    """GET /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.get_note",
        new_callable=AsyncMock,
    )
    async def test_get_note_returns_200(
        self, mock_get: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get.return_value = FAKE_NOTE_RESPONSE
        response = await client.get(f"{NOTES_BASE}/note-001")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == FAKE_NOTE_RESPONSE
        mock_get.assert_awaited_once_with("note-001", USER_ID)
        mock_log.set.assert_any_call(operation="get_note")
        mock_log.set.assert_any_call(note_id="note-001")
        mock_log.set.assert_any_call(outcome="success")

    @patch(
        "app.api.v1.endpoints.notes.get_note",
        new_callable=AsyncMock,
    )
    async def test_get_note_passthrough_service_httpexception(
        self, mock_get: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        """The service's 404 (Note not found) reaches the client unchanged."""
        mock_get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )
        response = await client.get(f"{NOTES_BASE}/missing")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Note not found"}
        mock_log.set.assert_called_once_with(operation="get_note")
        mock_log.error.assert_not_called()

    @patch(
        "app.api.v1.endpoints.notes.get_note",
        new_callable=AsyncMock,
    )
    async def test_get_note_service_error_returns_500(
        self, mock_get: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("Not found")
        response = await client.get(f"{NOTES_BASE}/nonexistent")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"detail": "Failed to retrieve note"}
        mock_log.set.assert_called_once_with(operation="get_note")
        mock_log.error.assert_called_once_with(
            f"{LogTag.API} Error getting note",
            note_id="nonexistent",
            user_id=USER_ID,
            error_type="Exception",
            error="Not found",
        )


class TestGetAllNotes:
    """GET /api/v1/notes"""

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_returns_200(
        self, mock_get_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get_all.return_value = [FAKE_NOTE_RESPONSE]
        response = await client.get(NOTES_BASE)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [FAKE_NOTE_RESPONSE]
        mock_get_all.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_any_call(operation="list_notes")
        mock_log.set.assert_any_call(result_count=1)
        mock_log.set.assert_any_call(outcome="success")

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_empty_list(
        self, mock_get_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get_all.return_value = []
        response = await client.get(NOTES_BASE)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        mock_log.set.assert_any_call(result_count=0)

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_passthrough_service_httpexception(
        self, mock_get_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get_all.side_effect = HTTPException(
            status_code=status.HTTP_418_IM_A_TEAPOT, detail="custom"
        )
        response = await client.get(NOTES_BASE)

        assert response.status_code == status.HTTP_418_IM_A_TEAPOT
        assert response.json() == {"detail": "custom"}
        mock_log.set.assert_called_once_with(operation="list_notes")
        mock_log.error.assert_not_called()

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_service_error_returns_500(
        self, mock_get_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_get_all.side_effect = Exception("DB down")
        response = await client.get(NOTES_BASE)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"detail": "Failed to retrieve notes"}
        mock_log.set.assert_called_once_with(operation="list_notes")
        mock_log.error.assert_called_once_with(
            f"{LogTag.API} Error listing notes",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )


class TestUpdateNote:
    """PUT /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_returns_200(
        self, mock_update: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        updated = {**FAKE_NOTE_RESPONSE, **UPDATED_NOTE_PAYLOAD}
        mock_update.return_value = updated
        response = await client.put(f"{NOTES_BASE}/note-001", json=UPDATED_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == updated
        mock_update.assert_awaited_once_with("note-001", NoteModel(**UPDATED_NOTE_PAYLOAD), USER_ID)
        mock_log.set.assert_any_call(operation="update_note")
        mock_log.set.assert_any_call(note_id="note-001")
        mock_log.set.assert_any_call(outcome="success")

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_passthrough_service_httpexception(
        self, mock_update: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        """The service's 404 (Note not found) reaches the client unchanged."""
        mock_update.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )
        response = await client.put(f"{NOTES_BASE}/missing", json=UPDATED_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Note not found"}
        mock_log.set.assert_called_once_with(operation="update_note")
        mock_log.error.assert_not_called()

    async def test_update_note_missing_fields_returns_422(self, client: AsyncClient):
        response = await client.put(f"{NOTES_BASE}/note-001", json={})
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_service_error_returns_500(
        self, mock_update: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_update.side_effect = Exception("Update failed")
        response = await client.put(f"{NOTES_BASE}/note-001", json=UPDATED_NOTE_PAYLOAD)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"detail": "Failed to update note"}
        mock_log.set.assert_called_once_with(operation="update_note")
        mock_log.error.assert_called_once_with(
            f"{LogTag.API} Error updating note",
            note_id="note-001",
            user_id=USER_ID,
            error_type="Exception",
            error="Update failed",
        )


class TestDeleteNote:
    """DELETE /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.delete_note",
        new_callable=AsyncMock,
    )
    async def test_delete_note_returns_204(
        self, mock_delete: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_delete.return_value = None
        response = await client.delete(f"{NOTES_BASE}/note-001")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_delete.assert_awaited_once_with("note-001", USER_ID)
        mock_log.set.assert_any_call(operation="delete_note")
        mock_log.set.assert_any_call(note_id="note-001")
        mock_log.set.assert_any_call(outcome="success")

    @patch(
        "app.api.v1.endpoints.notes.delete_note",
        new_callable=AsyncMock,
    )
    async def test_delete_note_passthrough_service_httpexception(
        self, mock_delete: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        """The service's 404 (Note not found) reaches the client unchanged."""
        mock_delete.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )
        response = await client.delete(f"{NOTES_BASE}/missing")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Note not found"}
        mock_log.set.assert_called_once_with(operation="delete_note")
        mock_log.error.assert_not_called()

    @patch(
        "app.api.v1.endpoints.notes.delete_note",
        new_callable=AsyncMock,
    )
    async def test_delete_note_service_error_returns_500(
        self, mock_delete: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("Delete failed")
        response = await client.delete(f"{NOTES_BASE}/note-001")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {"detail": "Failed to delete note"}
        mock_log.set.assert_called_once_with(operation="delete_note")
        mock_log.error.assert_called_once_with(
            f"{LogTag.API} Error deleting note",
            note_id="note-001",
            user_id=USER_ID,
            error_type="Exception",
            error="Delete failed",
        )
