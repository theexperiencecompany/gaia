"""Tests for app/services/dev_service.py — ``attach_dev_file`` routes the dev
upload through the production ``FileService.upload`` path unchanged."""

from datetime import UTC, datetime
import io
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
import pytest

from app.models.files_models import FileDocument
from app.models.user_models import UserDocument
from app.services.dev_service import attach_dev_file
from app.utils.errors import AppError

EMAIL = "dev@heygaia.io"
USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-dev-1"


def _document() -> FileDocument:
    return FileDocument(
        id="65f0000000000000000000aa",
        user_id=USER_ID,
        file_id="file-1",
        filename="a.pdf",
        type="pdf",
        size=10,
        url="https://x/a.pdf",
        created_at=datetime.now(UTC),
    )


def _upload() -> UploadFile:
    return UploadFile(filename="a.pdf", file=io.BytesIO(b"pdf"))


async def test_the_upload_is_handed_the_resolved_user_and_the_named_conversation() -> None:
    """The dev route owns only the email; every other argument is passed through."""
    document = _document()
    file = _upload()

    with (
        patch(
            "app.services.dev_service.user_repository.get_by_email",
            new_callable=AsyncMock,
            return_value=UserDocument(id=USER_ID, email=EMAIL),
        ),
        patch(
            "app.services.dev_service.FileService.upload",
            new_callable=AsyncMock,
            return_value=document,
        ) as mock_upload,
    ):
        result = await attach_dev_file(EMAIL, CONVERSATION_ID, file, 3)

    assert result is document
    mock_upload.assert_awaited_once_with(
        file=file,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        content_length=3,
    )


async def test_an_absent_content_length_is_forwarded_as_none() -> None:
    """A chunked upload has no declared length — the service must not invent one."""
    with (
        patch(
            "app.services.dev_service.user_repository.get_by_email",
            new_callable=AsyncMock,
            return_value=UserDocument(id=USER_ID, email=EMAIL),
        ),
        patch(
            "app.services.dev_service.FileService.upload",
            new_callable=AsyncMock,
            return_value=_document(),
        ) as mock_upload,
    ):
        await attach_dev_file(EMAIL, CONVERSATION_ID, _upload(), None)

    assert mock_upload.await_args.kwargs["content_length"] is None


async def test_an_unminted_email_never_reaches_the_upload() -> None:
    """No dev user means a 404 before any file work happens."""
    with (
        patch(
            "app.services.dev_service.user_repository.get_by_email",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.services.dev_service.FileService.upload", new_callable=AsyncMock) as mock_upload,
        pytest.raises(AppError) as excinfo,
    ):
        await attach_dev_file(EMAIL, CONVERSATION_ID, _upload(), 3)

    assert excinfo.value.status_code == 404
    mock_upload.assert_not_awaited()
