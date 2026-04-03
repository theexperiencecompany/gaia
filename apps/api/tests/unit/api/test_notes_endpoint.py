"""Unit tests for notes API endpoints.

Tests the notes CRUD endpoints with mocked service layer
to verify routing, status codes, response bodies, and validation.

Note: The notes endpoints do NOT have try/except blocks — exceptions
propagate to the global handler. With ``ASGITransport(raise_app_exceptions=True)``
(the default), these surface as raised exceptions in the test client rather than
500 responses. Tests for service errors therefore assert that the exception is raised.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

NOTES_BASE = "/api/v1/notes"

FAKE_NOTE_RESPONSE = {
    "id": "note-001",
    "content": "<p>Test note</p>",
    "plaintext": "Test note",
    "auto_created": False,
    "user_id": "507f1f77bcf86cd799439011",
    "title": None,
    "description": None,
}


@pytest.mark.unit
class TestCreateNote:
    """POST /api/v1/notes"""

    @patch(
        "app.api.v1.endpoints.notes.create_note_service",
        new_callable=AsyncMock,
    )
    async def test_create_note_returns_201(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = FAKE_NOTE_RESPONSE
        response = await client.post(
            NOTES_BASE,
            json={"content": "<p>Test note</p>", "plaintext": "Test note"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "note-001"
        assert data["content"] == "<p>Test note</p>"
        assert data["plaintext"] == "Test note"
        mock_create.assert_awaited_once()

    @patch(
        "app.api.v1.endpoints.notes.create_note_service",
        new_callable=AsyncMock,
    )
    async def test_create_note_passes_user_id(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = FAKE_NOTE_RESPONSE
        await client.post(
            NOTES_BASE,
            json={"content": "<p>Hello</p>", "plaintext": "Hello"},
        )
        args, _ = mock_create.call_args
        assert args[1] == "507f1f77bcf86cd799439011"

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
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.side_effect = Exception("DB write failed")
        response = await client.post(
            NOTES_BASE,
            json={"content": "<p>Test</p>", "plaintext": "Test"},
        )
        assert response.status_code == 500


@pytest.mark.unit
class TestGetNote:
    """GET /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.get_note",
        new_callable=AsyncMock,
    )
    async def test_get_note_returns_200(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = FAKE_NOTE_RESPONSE
        response = await client.get(f"{NOTES_BASE}/note-001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "note-001"
        mock_get.assert_awaited_once_with("note-001", "507f1f77bcf86cd799439011")

    @patch(
        "app.api.v1.endpoints.notes.get_note",
        new_callable=AsyncMock,
    )
    async def test_get_note_service_error_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("Not found")
        response = await client.get(f"{NOTES_BASE}/nonexistent")
        assert response.status_code == 500


@pytest.mark.unit
class TestGetAllNotes:
    """GET /api/v1/notes"""

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_returns_200(
        self, mock_get_all: AsyncMock, client: AsyncClient
    ):
        mock_get_all.return_value = [FAKE_NOTE_RESPONSE]
        response = await client.get(NOTES_BASE)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "note-001"

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_empty_list(
        self, mock_get_all: AsyncMock, client: AsyncClient
    ):
        mock_get_all.return_value = []
        response = await client.get(NOTES_BASE)
        assert response.status_code == 200
        assert response.json() == []

    @patch(
        "app.api.v1.endpoints.notes.get_all_notes",
        new_callable=AsyncMock,
    )
    async def test_get_all_notes_service_error_returns_500(
        self, mock_get_all: AsyncMock, client: AsyncClient
    ):
        mock_get_all.side_effect = Exception("DB down")
        response = await client.get(NOTES_BASE)
        assert response.status_code == 500


@pytest.mark.unit
class TestUpdateNote:
    """PUT /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_returns_200(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        updated = {
            **FAKE_NOTE_RESPONSE,
            "content": "<p>Updated</p>",
            "plaintext": "Updated",
        }
        mock_update.return_value = updated
        response = await client.put(
            f"{NOTES_BASE}/note-001",
            json={"content": "<p>Updated</p>", "plaintext": "Updated"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "<p>Updated</p>"
        assert data["plaintext"] == "Updated"

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_passes_correct_args(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = FAKE_NOTE_RESPONSE
        await client.put(
            f"{NOTES_BASE}/note-001",
            json={"content": "<p>Updated</p>", "plaintext": "Updated"},
        )
        args, _ = mock_update.call_args
        assert args[0] == "note-001"
        assert args[2] == "507f1f77bcf86cd799439011"

    async def test_update_note_missing_fields_returns_422(self, client: AsyncClient):
        response = await client.put(f"{NOTES_BASE}/note-001", json={})
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.notes.update_note",
        new_callable=AsyncMock,
    )
    async def test_update_note_service_error_returns_500(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.side_effect = Exception("Update failed")
        response = await client.put(
            f"{NOTES_BASE}/note-001",
            json={"content": "<p>Updated</p>", "plaintext": "Updated"},
        )
        assert response.status_code == 500


@pytest.mark.unit
class TestDeleteNote:
    """DELETE /api/v1/notes/{note_id}"""

    @patch(
        "app.api.v1.endpoints.notes.delete_note",
        new_callable=AsyncMock,
    )
    async def test_delete_note_returns_204(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = None
        response = await client.delete(f"{NOTES_BASE}/note-001")
        assert response.status_code == 204
        mock_delete.assert_awaited_once_with("note-001", "507f1f77bcf86cd799439011")

    @patch(
        "app.api.v1.endpoints.notes.delete_note",
        new_callable=AsyncMock,
    )
    async def test_delete_note_service_error_returns_500(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("Delete failed")
        response = await client.delete(f"{NOTES_BASE}/note-001")
        assert response.status_code == 500
