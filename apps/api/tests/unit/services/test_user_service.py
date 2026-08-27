"""Unit tests for user service operations."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.user_models import UserDocument, UserUpdateResponse
from app.services.user_service import get_user_by_id, update_user_profile

UPDATED_AT = datetime(2025, 7, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_repo() -> Iterator[tuple[AsyncMock, AsyncMock]]:
    with (
        patch("app.services.user_service.user_repository.get", new_callable=AsyncMock) as mock_get,
        patch(
            "app.services.user_service.user_repository.update", new_callable=AsyncMock
        ) as mock_update,
    ):
        yield mock_get, mock_update


@pytest.fixture
def sample_user() -> UserDocument:
    return UserDocument(
        id=str(ObjectId()),
        email="alice@example.com",
        name="Alice",
        picture="https://example.com/alice.jpg",
    )


class TestGetUserById:
    async def test_returns_exact_legacy_dict(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user

        result = await get_user_by_id(sample_user.id)

        assert result == {
            "email": "alice@example.com",
            "name": "Alice",
            "picture": "https://example.com/alice.jpg",
            "_id": sample_user.id,
        }

    async def test_queries_repository_with_exact_id(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user

        await get_user_by_id(sample_user.id)

        mock_get.assert_awaited_once_with(sample_user.id)

    async def test_returns_none_when_not_found(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.return_value = None

        result = await get_user_by_id(str(ObjectId()))
        assert result is None

    async def test_raises_404_on_exception(self, mock_repo):
        mock_get, _ = mock_repo
        original = Exception("DB error")
        mock_get.side_effect = original

        with pytest.raises(HTTPException) as exc_info:
            await get_user_by_id("invalid_id")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"
        assert exc_info.value.__cause__ is original

    async def test_logs_context_and_error(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user

        with patch("app.services.user_service.log") as mock_log:
            await get_user_by_id(sample_user.id)

        mock_log.set.assert_called_once_with(component="user_service", user_id=sample_user.id)

        failure = Exception("DB error")
        mock_get.side_effect = failure
        with patch("app.services.user_service.log") as mock_log, pytest.raises(HTTPException):
            await get_user_by_id(sample_user.id)

        mock_log.error.assert_called_once_with(
            "Error fetching user",
            user_id=sample_user.id,
            error="DB error",
            error_type="Exception",
        )


class TestUpdateUserProfile:
    async def test_updates_name(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        updated_user = sample_user.model_copy(
            update={"name": "Alice Updated", "updated_at": UPDATED_AT}
        )
        mock_update.return_value = updated_user

        result = await update_user_profile(sample_user.id, name="Alice Updated")

        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice Updated",
            email="alice@example.com",
            picture="https://example.com/alice.jpg",
            updated_at=UPDATED_AT,
        )

        mock_update.assert_awaited_once()
        update_arg = mock_update.call_args.args[1]
        assert update_arg.model_dump(exclude_unset=True) == {"name": "Alice Updated"}

    async def test_none_name_writes_nothing_and_returns_current_profile(
        self, mock_repo, sample_user
    ):
        """name=None must skip the name branch entirely — no update call."""
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user

        result = await update_user_profile(sample_user.id)

        mock_update.assert_not_called()
        assert result == UserUpdateResponse(
            user_id=sample_user.id,
            name="Alice",
            email="alice@example.com",
            picture="https://example.com/alice.jpg",
            updated_at=None,
        )

    async def test_a_legacy_account_with_no_name_or_email_degrades_to_empty_strings(
        self, mock_repo
    ):
        """The response schema types name/email as `str`, but a legacy account
        can carry neither. Both degrade to "" — not to None (which would fail
        validation and 500 the whole update) and not to any other filler."""
        mock_get, mock_update = mock_repo
        bare = UserDocument(id=str(ObjectId()), email=None, name=None)
        mock_get.return_value = bare
        mock_update.return_value = bare.model_copy(update={"updated_at": UPDATED_AT})

        result = await update_user_profile(bare.id, name="Nino")

        assert result.name == ""
        assert result.email == ""

    async def test_raises_404_when_user_not_found(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="New Name")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_strips_whitespace_from_name(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        mock_update.return_value = sample_user.model_copy(update={"name": "Trimmed"})

        await update_user_profile(sample_user.id, name="  Trimmed  ")

        update_arg = mock_update.call_args.args[1]
        assert update_arg.model_dump(exclude_unset=True)["name"] == "Trimmed"

    async def test_skips_empty_name(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user

        # An all-whitespace name writes nothing — no update call, no updated_at bump.
        await update_user_profile(sample_user.id, name="   ")

        mock_update.assert_not_called()

    async def test_only_allowlisted_fields_are_written(self, mock_repo, sample_user):
        """Only name/picture may be set — UserUpdate forbids arbitrary fields."""
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        mock_update.return_value = sample_user

        await update_user_profile(sample_user.id, name="Alice")

        update_arg = mock_update.call_args.args[1]
        assert set(update_arg.model_dump(exclude_unset=True)) <= {"name", "picture"}

    async def test_picture_upload_success_sets_picture_field(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        uploaded_url = "https://res.cloudinary.com/alice.jpg"
        updated_user = sample_user.model_copy(
            update={"picture": uploaded_url, "updated_at": UPDATED_AT}
        )
        mock_update.return_value = updated_user

        with patch(
            "app.services.user_service.upload_user_picture", new_callable=AsyncMock
        ) as mock_upload:
            mock_upload.return_value = uploaded_url
            result = await update_user_profile(sample_user.id, picture_data=b"fake_image")

        # public_id is derived from the email: @ -> _at_, . -> _dot_, prefixed user_
        mock_upload.assert_awaited_once_with(b"fake_image", "user_alice_at_example_dot_com")
        update_arg = mock_update.call_args.args[1]
        assert update_arg.model_dump(exclude_unset=True) == {"picture": uploaded_url}
        assert result.picture == uploaded_url
        assert result.updated_at == UPDATED_AT

    async def test_public_id_handles_missing_email(self, mock_repo):
        mock_get, mock_update = mock_repo
        user_no_email = UserDocument(id=str(ObjectId()), email=None, name="No Email")
        mock_get.return_value = user_no_email
        mock_update.return_value = user_no_email

        with patch(
            "app.services.user_service.upload_user_picture", new_callable=AsyncMock
        ) as mock_upload:
            mock_upload.return_value = "https://res.cloudinary.com/pic.jpg"
            await update_user_profile(user_no_email.id, picture_data=b"fake_image")

        mock_upload.assert_awaited_once_with(b"fake_image", "user_")

    async def test_empty_picture_bytes_skip_upload(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user

        with patch(
            "app.services.user_service.upload_user_picture", new_callable=AsyncMock
        ) as mock_upload:
            await update_user_profile(sample_user.id, picture_data=b"")

        mock_upload.assert_not_called()
        mock_update.assert_not_called()

    async def test_raises_500_on_picture_upload_failure(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user
        original = Exception("Upload failed")

        with patch(
            "app.services.user_service.upload_user_picture",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_user_profile(sample_user.id, picture_data=b"fake_image")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to upload profile picture"
        assert exc_info.value.__cause__ is original

    async def test_raises_404_when_update_returns_none(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        mock_update.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(sample_user.id, name="Alice Updated")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found after update"

    async def test_raises_500_on_unexpected_error(self, mock_repo):
        mock_get, _ = mock_repo
        original = Exception("Unexpected")
        mock_get.side_effect = original

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="Test")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to update profile"
        assert exc_info.value.__cause__ is original

    async def test_logs_operation_context(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        mock_update.return_value = sample_user

        with patch("app.services.user_service.log") as mock_log:
            await update_user_profile(sample_user.id, name="Alice")

        mock_log.set.assert_called_once_with(
            component="user_service",
            user_id=sample_user.id,
            operation="update_profile",
            has_picture=False,
        )

        with (
            patch("app.services.user_service.log") as mock_log,
            patch(
                "app.services.user_service.upload_user_picture", new_callable=AsyncMock
            ) as mock_upload,
        ):
            mock_upload.return_value = "https://res.cloudinary.com/pic.jpg"
            await update_user_profile(sample_user.id, picture_data=b"fake_image")

        assert mock_log.set.call_args.kwargs["has_picture"] is True
