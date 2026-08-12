"""Unit tests for file upload/update/delete API endpoints.

Tests the file endpoints with a mocked ``FileService`` to verify routing,
status codes, response bodies, validation, and conversation ownership checks.
"""

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.files_models import FileDocument
from app.schemas.file import FileDeletedResponse

FILE_BASE = "/api/v1"


def _file_doc(**overrides: object) -> FileDocument:
    """A stored file document as ``FileService.update`` returns it."""
    data: dict[str, object] = {
        "id": "0" * 24,
        "file_id": "file-001",
        "user_id": "507f1f77bcf86cd799439011",
        "filename": "doc.pdf",
        "type": "application/pdf",
        "size": 10,
        "url": "https://cdn.example.com/doc.pdf",
        "public_id": "pub-id",
        "description": "desc",
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
    }
    data.update(overrides)
    return FileDocument.model_validate(data)


class TestUploadFile:
    """POST /api/v1/upload"""

    @patch(
        "app.api.v1.endpoints.file.FileService.upload",
        new_callable=AsyncMock,
    )
    async def test_upload_file_returns_201(self, mock_upload: AsyncMock, client: AsyncClient):
        mock_upload.return_value = _file_doc(
            file_id="file-001",
            url="https://cdn.example.com/file.png",
            filename="test.png",
            type="image",
        )
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
        "app.api.v1.endpoints.file.conversation_repository",
    )
    @patch(
        "app.api.v1.endpoints.file.FileService.upload",
        new_callable=AsyncMock,
    )
    async def test_upload_file_with_conversation_id(
        self, mock_upload: AsyncMock, mock_convs, client: AsyncClient
    ):
        mock_upload.return_value = _file_doc(
            file_id="file-002",
            url="https://cdn.example.com/doc.pdf",
            filename="doc.pdf",
            type="file",
        )
        # Simulate that the conversation is owned by the authenticated user.
        mock_convs.exists = AsyncMock(return_value=True)
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
        "app.api.v1.endpoints.file.conversation_repository",
    )
    @patch(
        "app.api.v1.endpoints.file.FileService.upload",
        new_callable=AsyncMock,
    )
    async def test_upload_file_unowned_conversation_returns_403(
        self, mock_upload: AsyncMock, mock_convs, client: AsyncClient
    ):
        """Uploads targeting a conversation the user does not own are rejected."""
        mock_convs.exists = AsyncMock(return_value=False)
        file_content = BytesIO(b"fake pdf data")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("doc.pdf", file_content, "application/pdf")},
            data={"conversation_id": "conv-not-mine"},
        )
        assert response.status_code == 403
        mock_upload.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.file.FileService.upload",
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
        "app.api.v1.endpoints.file.FileService.upload",
        new_callable=AsyncMock,
    )
    async def test_upload_file_reports_the_stored_content_type(
        self, mock_upload: AsyncMock, client: AsyncClient
    ):
        """The response's ``type`` mirrors the MIME type persisted on the document."""
        mock_upload.return_value = _file_doc(
            file_id="file-003",
            url="https://cdn.example.com/data.csv",
            filename="data.csv",
            type="text/csv",
        )
        file_content = BytesIO(b"col1,col2\na,b")
        response = await client.post(
            f"{FILE_BASE}/upload",
            files={"file": ("data.csv", file_content, "text/csv")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "text/csv"


class TestUpdateFile:
    """PUT /api/v1/{file_id}"""

    @patch(
        "app.api.v1.endpoints.file.FileService.update",
        new_callable=AsyncMock,
    )
    async def test_update_file_returns_200(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = _file_doc(description="Updated description")
        response = await client.put(
            f"{FILE_BASE}/file-001",
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["file_id"] == "file-001"
        assert data["description"] == "Updated description"
        assert data["filename"] == "doc.pdf"
        assert data["url"] == "https://cdn.example.com/doc.pdf"
        assert data["created_at"] == "2025-01-01T00:00:00Z"

    @patch(
        "app.api.v1.endpoints.file.FileService.update",
        new_callable=AsyncMock,
    )
    async def test_update_file_passes_correct_args(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = _file_doc()
        await client.put(
            f"{FILE_BASE}/file-001",
            json={"description": "New desc"},
        )
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["file_id"] == "file-001"
        assert call_kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert call_kwargs["update_data"] == {"description": "New desc"}

    @patch(
        "app.api.v1.endpoints.file.FileService.update",
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


class TestDeleteFile:
    """DELETE /api/v1/{file_id}"""

    @patch(
        "app.api.v1.endpoints.file.FileService.delete",
        new_callable=AsyncMock,
    )
    async def test_delete_file_returns_200(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = FileDeletedResponse(
            message="File deleted successfully",
            file_id="file-001",
            filename="doc.pdf",
        )
        response = await client.delete(f"{FILE_BASE}/file-001")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "message": "File deleted successfully",
            "file_id": "file-001",
            "filename": "doc.pdf",
        }

    @patch(
        "app.api.v1.endpoints.file.FileService.delete",
        new_callable=AsyncMock,
    )
    async def test_delete_file_passes_user_id(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = FileDeletedResponse(
            message="File deleted successfully",
            file_id="file-001",
            filename="doc.pdf",
        )
        await client.delete(f"{FILE_BASE}/file-001")
        call_kwargs = mock_delete.call_args.kwargs
        assert call_kwargs["file_id"] == "file-001"
        assert call_kwargs["user_id"] == "507f1f77bcf86cd799439011"

    @patch(
        "app.api.v1.endpoints.file.FileService.delete",
        new_callable=AsyncMock,
    )
    async def test_delete_file_service_error_returns_500(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("Delete failed")
        response = await client.delete(f"{FILE_BASE}/file-001")
        assert response.status_code == 500
