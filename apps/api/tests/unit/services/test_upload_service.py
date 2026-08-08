"""Unit tests for the Cloudinary upload pipeline (upload_service)."""

from unittest.mock import MagicMock, patch

import cloudinary.exceptions
from fastapi import HTTPException
import pytest

from app.services.upload_service import upload_file_to_cloudinary

_MOD = "app.services.upload_service"


@pytest.fixture
def mock_upload():
    with patch(f"{_MOD}.cloudinary.uploader.upload") as m:
        m.return_value = {"secure_url": "https://res.cloudinary.com/x/abc.png"}
        yield m


class TestUploadFileToCloudinary:
    def test_uploads_file_data(self, mock_upload):
        url = upload_file_to_cloudinary("my-public-id", file_data=b"binary payload")

        assert url == "https://res.cloudinary.com/x/abc.png"
        assert mock_upload.call_args.args == (b"binary payload",)
        assert mock_upload.call_args.kwargs == {
            "resource_type": "auto",
            "public_id": "my-public-id",
            "overwrite": True,
        }

    def test_uploads_existing_file_path(self, mock_upload):
        with patch(f"{_MOD}.os.path.exists", return_value=True):
            url = upload_file_to_cloudinary("my-public-id", file_path="/tmp/photo.png")

        assert url == "https://res.cloudinary.com/x/abc.png"
        assert mock_upload.call_args.args == ("/tmp/photo.png",)

    def test_raises_400_when_no_source(self, mock_upload):
        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("my-public-id")

        assert exc_info.value.status_code == 400
        assert "file_data or file_path" in exc_info.value.detail
        mock_upload.assert_not_called()

    def test_raises_400_when_both_sources(self, mock_upload):
        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("my-public-id", file_data=b"x", file_path="/tmp/photo.png")

        assert exc_info.value.status_code == 400
        assert "both" in exc_info.value.detail
        mock_upload.assert_not_called()

    def test_raises_400_when_public_id_missing(self, mock_upload):
        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("", file_data=b"x")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "public_id is required"
        mock_upload.assert_not_called()

    def test_raises_404_when_file_path_missing(self, mock_upload):
        with patch(f"{_MOD}.os.path.exists", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                upload_file_to_cloudinary("my-public-id", file_path="/tmp/ghost.png")

        assert exc_info.value.status_code == 404
        assert "/tmp/ghost.png" in exc_info.value.detail
        mock_upload.assert_not_called()

    def test_raises_500_when_secure_url_missing(self, mock_upload):
        """The missing-secure_url guard raises inside the try, so the generic
        except rewraps it into the generic 500 — that is the observable contract."""
        mock_upload.return_value = {"url": "http://insecure.example"}

        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("my-public-id", file_data=b"x")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An unexpected error occurred during file upload"

    def test_raises_500_on_cloudinary_error(self, mock_upload):
        mock_upload.side_effect = cloudinary.exceptions.Error("upstream nope")

        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("my-public-id", file_data=b"x")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to upload file to Cloudinary"

    def test_raises_500_on_unexpected_error(self, mock_upload):
        mock_upload.side_effect = MagicMock(side_effect=RuntimeError("boom"))

        with pytest.raises(HTTPException) as exc_info:
            upload_file_to_cloudinary("my-public-id", file_data=b"x")

        assert exc_info.value.status_code == 500
        assert "unexpected error" in exc_info.value.detail
