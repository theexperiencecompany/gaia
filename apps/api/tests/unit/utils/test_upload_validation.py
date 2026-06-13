"""Unit tests for upload validation helpers."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
import pytest

from app.utils.upload_validation import validate_upload, verify_webp_container


@pytest.mark.unit
class TestVerifyWebpContainer:
    def test_valid_webp_container_passes(self) -> None:
        verify_webp_container(b"RIFF\x10\x00\x00\x00WEBPVP8 ")

    @pytest.mark.parametrize(
        "content",
        [
            b"RIFF\x10\x00\x00\x00AVI ",
            b"XXXX\x10\x00\x00\x00WEBPVP8 ",
            b"RIFF",
            b"",
        ],
    )
    def test_invalid_webp_container_raises_400(self, content: bytes) -> None:
        with pytest.raises(HTTPException) as exc_info:
            verify_webp_container(content)

        assert exc_info.value.status_code == 400
        assert "does not match" in exc_info.value.detail


@pytest.mark.unit
class TestValidateUploadWebp:
    pytestmark = pytest.mark.asyncio

    async def test_valid_webp_upload_passes(self) -> None:
        file = MagicMock()
        file.filename = "image.webp"
        file.content_type = "image/webp"
        file.read = AsyncMock(return_value=b"RIFF\x10\x00\x00\x00WEBPVP8 ")

        content, content_type, resource_type = await validate_upload(file, content_length=None)

        assert content == b"RIFF\x10\x00\x00\x00WEBPVP8 "
        assert content_type == "image/webp"
        assert resource_type == "image"

    async def test_rejects_riff_file_claimed_as_webp(self) -> None:
        file = MagicMock()
        file.filename = "video.webp"
        file.content_type = "image/webp"
        file.read = AsyncMock(return_value=b"RIFF\x10\x00\x00\x00AVI LIST")

        with pytest.raises(HTTPException) as exc_info:
            await validate_upload(file, content_length=None)

        assert exc_info.value.status_code == 400
        assert "does not match" in exc_info.value.detail
