"""Unit tests for file upload/update/delete API endpoints.

Tests the file endpoints with mocked service layer
to verify routing, status codes, response bodies, and validation.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# Note: The file endpoints do NOT have try/except blocks, so unhandled
# exceptions propagate to the global handler. With ASGITransport's default
# raise_app_exceptions=True, these surface as raised exceptions in the client.

FILE_BASE = "/api/v1"


@pytest.mark.unit
class TestUploadFile:
    """POST /api/v1/upload"""

    @patch(
        "app.api.v1.endpoints.file.upload_file_service",
        new_callable=AsyncMock,
    )
    async def test_upload_file_returns_201(
        self, mock_upload: AsyncMock, client: AsyncClient
    ):
        mock_upload.return_value = {
            "file_id": "file-001",
            "url": "https://cdn.example.com/file.png",
            "filename": "test.png",
            "type": "image",
        }
        file_content = BytesIO(b"fake image data")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("test.png", file_content, "image/png")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["fileId"] == "file-001"
        assert data["url"] == "https://cdn.example.com/file.png"
        assert data["filename"] == "test.png"
        assert data["type"] == "image"
        assert data["message"] == "File uploaded successfully"

    @patch(
        "app.api.v1.endpoints.file.upload_file_service",
        new_callable=AsyncMock,
    )
    async def test_upload_file_with_conversation_id(
        self, mock_upload: AsyncMock, client: AsyncClient
    ):
        mock_upload.return_value = {
            "file_id": "file-002",
            "url": "https://cdn.example.com/doc.pdf",
            "filename": "doc.pdf",
            "type": "file",
        }
        file_content = BytesIO(b"fake pdf data")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("doc.pdf", file_content, "application/pdf")},
            data={"conversation_id": "conv-123"},
        )
        assert response.status_code == 201
        mock_upload.assert_awaited_once()
        call_kwargs = mock_upload.call_args.kwargs
        assert call_kwargs["conversation_id"] == "conv-123"

    @patch(
        "app.api.v1.endpoints.file.upload_file_service",
        new_callable=AsyncMock,
    )
    async def test_upload_file_service_error_returns_500(
        self, mock_upload: AsyncMock, client: AsyncClient
    ):
        mock_upload.side_effect = Exception("Upload failed")
        file_content = BytesIO(b"data")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("test.txt", file_content, "text/plain")},
        )
        assert response.status_code == 500

    async def test_upload_file_missing_file_returns_422(self, client: AsyncClient):
        response = await client.post(f"{FILE_BASE}/upload")
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.file.upload_file_service",
        new_callable=AsyncMock,
    )
    async def test_upload_file_default_type_is_file(
        self, mock_upload: AsyncMock, client: AsyncClient
    ):
        mock_upload.return_value = {
            "file_id": "file-003",
            "url": "https://cdn.example.com/data.csv",
            "filename": "data.csv",
        }
        file_content = BytesIO(b"col1,col2\na,b")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("data.csv", file_content, "text/csv")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "file"


@pytest.mark.unit
class TestUpdateFile:
    """PUT /api/v1/{file_id}"""

    @patch(
        "app.api.v1.endpoints.file.update_file_service",
        new_callable=AsyncMock,
    )
    async def test_update_file_returns_200(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = {
            "file_id": "file-001",
            "description": "Updated description",
        }
        response = await client.put(
            f"{FILE_BASE}/file-001",
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["file_id"] == "file-001"
        assert data["description"] == "Updated description"

    @patch(
        "app.api.v1.endpoints.file.update_file_service",
        new_callable=AsyncMock,
    )
    async def test_update_file_passes_correct_args(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = {"file_id": "file-001"}
        await client.put(
            f"{FILE_BASE}/file-001",
            json={"description": "New desc"},
        )
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["file_id"] == "file-001"
        assert call_kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert call_kwargs["update_data"] == {"description": "New desc"}

    @patch(
        "app.api.v1.endpoints.file.update_file_service",
        new_callable=AsyncMock,
    )
    async def test_update_file_service_error_returns_500(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.side_effect = Exception("Update failed")
        response = await client.put(
            f"{FILE_BASE}/file-001",
            json={"description": "New desc"},
        )
        assert response.status_code == 500


@pytest.mark.unit
class TestDeleteFile:
    """DELETE /api/v1/{file_id}"""

    @patch(
        "app.api.v1.endpoints.file.delete_file_service",
        new_callable=AsyncMock,
    )
    async def test_delete_file_returns_200(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = {
            "message": "File deleted successfully",
            "file_id": "file-001",
        }
        response = await client.delete(f"{FILE_BASE}/file-001")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "File deleted successfully"

    @patch(
        "app.api.v1.endpoints.file.delete_file_service",
        new_callable=AsyncMock,
    )
    async def test_delete_file_passes_user_id(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = {"message": "ok"}
        await client.delete(f"{FILE_BASE}/file-001")
        call_kwargs = mock_delete.call_args.kwargs
        assert call_kwargs["file_id"] == "file-001"
        assert call_kwargs["user_id"] == "507f1f77bcf86cd799439011"

    @patch(
        "app.api.v1.endpoints.file.delete_file_service",
        new_callable=AsyncMock,
    )
    async def test_delete_file_service_error_returns_500(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("Delete failed")
        response = await client.delete(f"{FILE_BASE}/file-001")
        assert response.status_code == 500
