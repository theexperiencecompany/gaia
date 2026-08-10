"""Unit tests for user service operations.

The service delegates persistence to ``user_repository`` and picture uploads
to ``upload_user_picture`` (Cloudinary); both seams are mocked. These tests
pin the service's own contract exactly: delegation arguments, the
``user_to_legacy_dict`` bridge shape (string ``_id``), the not-found -> 404
and failure -> 500 mappings with their exact details, the exact Cloudinary
``public_id`` derivation, the no-op write path (blank name / no picture must
not touch the DB), and the wide-event log lines.
"""

from datetime import UTC, datetime
from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.user_models import UserDocument, UserUpdate, UserUpdateResponse
from app.services.user_service import get_user_by_id, update_user_profile

CLOUDINARY_URL = "https://res.cloudinary.com/gaia/image/upload/v1/user_alice_at_example_dot_com.jpg"
# Fixed timestamp so the response's updated_at passthrough is pinned exactly.
UPDATED_AT = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)


def _user(**overrides: Any) -> UserDocument:
    return UserDocument.model_validate(
        {
            "id": str(ObjectId()),
            "email": "alice@example.com",
            "name": "Alice",
            "picture": "https://example.com/alice.jpg",
            **overrides,
        }
    )


@pytest.fixture
def seams() -> SimpleNamespace:
    with (
        patch("app.services.user_service.user_repository.get", new_callable=AsyncMock) as mock_get,
        patch(
            "app.services.user_service.user_repository.update", new_callable=AsyncMock
        ) as mock_update,
        patch(
            "app.services.user_service.upload_user_picture", new_callable=AsyncMock
        ) as mock_upload,
        patch("app.services.user_service.log") as mock_log,
    ):
        yield SimpleNamespace(
            get=mock_get, update=mock_update, upload=mock_upload, log=mock_log
        )


@pytest.fixture
def sample_user() -> UserDocument:
    return _user()


class TestGetUserById:
    async def test_returns_legacy_dict_with_string_id(self, seams, sample_user):
        seams.get.return_value = sample_user

        result = await get_user_by_id(sample_user.id)

        # user_to_legacy_dict bridge: raw-style dict, string _id, None fields dropped.
        assert result == {
            "_id": sample_user.id,
            "email": "alice@example.com",
            "name": "Alice",
            "picture": "https://example.com/alice.jpg",
        }
        seams.get.assert_awaited_once_with(sample_user.id)
        seams.log.set.assert_called_once_with(component="user_service", user_id=sample_user.id)
        seams.log.error.assert_not_called()

    async def test_returns_none_when_not_found(self, seams):
        seams.get.return_value = None
        user_id = str(ObjectId())

        result = await get_user_by_id(user_id)

        assert result is None
        seams.get.assert_awaited_once_with(user_id)
        seams.log.set.assert_called_once_with(component="user_service", user_id=user_id)

    async def test_raises_404_with_exact_detail_on_error(self, seams):
        seams.get.side_effect = Exception("DB error")
        user_id = str(ObjectId())

        with pytest.raises(HTTPException) as exc_info:
            await get_user_by_id(user_id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"
        seams.log.error.assert_called_once_with(
            "Error fetching user",
            user_id=user_id,
            error="DB error",
            error_type="Exception",
        )


class TestUpdateUserProfile:
    async def test_updates_name_exact(self, seams, sample_user):
        seams.get.return_value = sample_user
        updated = sample_user.model_copy(update={"name": "Alice Updated", "updated_at": UPDATED_AT})
        seams.update.return_value = updated

        result = await update_user_profile(sample_user.id, name="Alice Updated")

        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice Updated",
            email="alice@example.com",
            picture="https://example.com/alice.jpg",
            updated_at=UPDATED_AT,
        )
        seams.get.assert_awaited_once_with(sample_user.id)
        seams.update.assert_awaited_once_with(sample_user.id, UserUpdate(name="Alice Updated"))
        seams.log.set.assert_called_once_with(
            component="user_service",
            user_id=sample_user.id,
            operation="update_profile",
            has_picture=False,
        )
        seams.log.error.assert_not_called()

    async def test_strips_whitespace_from_name(self, seams, sample_user):
        seams.get.return_value = sample_user
        seams.update.return_value = sample_user.model_copy(update={"name": "Trimmed"})

        await update_user_profile(sample_user.id, name="  Trimmed  ")

        seams.update.assert_awaited_once_with(sample_user.id, UserUpdate(name="Trimmed"))

    async def test_skips_blank_name_without_writing(self, seams, sample_user):
        seams.get.return_value = sample_user

        # An all-whitespace name writes nothing — no update call, no updated_at bump.
        result = await update_user_profile(sample_user.id, name="   ")

        seams.update.assert_not_called()
        seams.upload.assert_not_called()
        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice",
            email="alice@example.com",
            picture="https://example.com/alice.jpg",
        )
        seams.log.set.assert_called_once_with(
            component="user_service",
            user_id=sample_user.id,
            operation="update_profile",
            has_picture=False,
        )

    async def test_skips_none_name_without_writing(self, seams, sample_user):
        seams.get.return_value = sample_user

        result = await update_user_profile(sample_user.id)

        seams.update.assert_not_called()
        seams.upload.assert_not_called()
        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice",
            email="alice@example.com",
            picture="https://example.com/alice.jpg",
        )
        seams.log.set.assert_called_once_with(
            component="user_service",
            user_id=sample_user.id,
            operation="update_profile",
            has_picture=False,
        )

    async def test_updates_picture_with_exact_public_id(self, seams, sample_user):
        seams.get.return_value = sample_user
        seams.upload.return_value = CLOUDINARY_URL
        seams.update.return_value = sample_user.model_copy(
            update={"picture": CLOUDINARY_URL, "updated_at": UPDATED_AT}
        )
        picture_bytes = b"\x89PNG\r\n\x1a\n fake-image-bytes"

        result = await update_user_profile(sample_user.id, picture_data=picture_bytes)

        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice",
            email="alice@example.com",
            picture=CLOUDINARY_URL,
            updated_at=UPDATED_AT,
        )
        # public_id derivation: user_<email with @ -> _at_ and . -> _dot_>
        seams.upload.assert_awaited_once_with(picture_bytes, "user_alice_at_example_dot_com")
        seams.update.assert_awaited_once_with(sample_user.id, UserUpdate(picture=CLOUDINARY_URL))
        seams.log.set.assert_called_once_with(
            component="user_service",
            user_id=sample_user.id,
            operation="update_profile",
            has_picture=True,
        )

    async def test_picture_public_id_when_email_missing(self, seams):
        user = _user(email=None)
        seams.get.return_value = user
        seams.upload.return_value = CLOUDINARY_URL
        # The response model requires a non-null email, so the updated doc must
        # carry one — the public_id seam is what this test pins, not the response.
        seams.update.return_value = user.model_copy(
            update={"email": "alice@example.com", "picture": CLOUDINARY_URL, "updated_at": UPDATED_AT}
        )

        result = await update_user_profile(user.id, picture_data=b"image")

        # No email -> empty replacement source, public_id is just the prefix.
        seams.upload.assert_awaited_once_with(b"image", "user_")
        assert result == UserUpdateResponse(
            user_id=user.id,
            name="Alice",
            email="alice@example.com",
            picture=CLOUDINARY_URL,
            updated_at=UPDATED_AT,
        )

    async def test_updates_name_and_picture_together(self, seams, sample_user):
        seams.get.return_value = sample_user
        seams.upload.return_value = CLOUDINARY_URL
        seams.update.return_value = sample_user.model_copy(
            update={"name": "Alice Updated", "picture": CLOUDINARY_URL, "updated_at": UPDATED_AT}
        )

        result = await update_user_profile(sample_user.id, name="Alice Updated", picture_data=b"image")

        seams.upload.assert_awaited_once_with(b"image", "user_alice_at_example_dot_com")
        seams.update.assert_awaited_once_with(
            sample_user.id, UserUpdate(name="Alice Updated", picture=CLOUDINARY_URL)
        )
        assert result.updated_at == UPDATED_AT

    async def test_raises_500_with_exact_detail_on_upload_failure(self, seams, sample_user):
        seams.get.return_value = sample_user
        seams.upload.side_effect = Exception("Upload failed")

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(sample_user.id, picture_data=b"fake")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to upload profile picture"
        seams.log.error.assert_called_once_with(
            "Error uploading profile picture",
            error="Upload failed",
            error_type="Exception",
            user_id=sample_user.id,
        )

    async def test_raises_404_when_update_returns_none(self, seams, sample_user):
        seams.get.return_value = sample_user
        seams.update.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(sample_user.id, name="Alice")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found after update"

    async def test_raises_404_with_exact_detail_when_user_not_found(self, seams):
        seams.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="New Name")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_raises_500_with_exact_detail_on_unexpected_error(self, seams):
        seams.get.side_effect = Exception("Unexpected")
        user_id = str(ObjectId())

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(user_id, name="Test")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to update profile"
        seams.log.error.assert_called_once_with(
            "Error updating user profile",
            error="Unexpected",
            error_type="Exception",
            user_id=user_id,
        )
