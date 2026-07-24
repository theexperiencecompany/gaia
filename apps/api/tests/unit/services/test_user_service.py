"""Unit tests for user service operations."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.user_models import UserDocument
from app.services.user_service import get_user_by_id, update_user_profile


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


@pytest.mark.unit
class TestGetUserById:
    async def test_returns_user_with_string_id(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user

        result = await get_user_by_id(sample_user.id)

        assert result is not None
        assert result["_id"] == sample_user.id
        assert result["email"] == "alice@example.com"

    async def test_returns_none_when_not_found(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.return_value = None

        result = await get_user_by_id(str(ObjectId()))
        assert result is None

    async def test_raises_404_on_exception(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.side_effect = Exception("DB error")

        with pytest.raises(HTTPException) as exc_info:
            await get_user_by_id("invalid_id")

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestUpdateUserProfile:
    async def test_updates_name(self, mock_repo, sample_user):
        mock_get, mock_update = mock_repo
        mock_get.return_value = sample_user
        mock_update.return_value = sample_user.model_copy(update={"name": "Alice Updated"})

        result = await update_user_profile(sample_user.id, name="Alice Updated")

        assert result["name"] == "Alice Updated"
        assert result["user_id"] == sample_user.id

        update_arg = mock_update.call_args.args[1]
        assert update_arg.model_dump(exclude_unset=True) == {"name": "Alice Updated"}

    async def test_raises_404_when_user_not_found(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="New Name")

        assert exc_info.value.status_code == 404

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

    async def test_raises_500_on_picture_upload_failure(self, mock_repo, sample_user):
        mock_get, _ = mock_repo
        mock_get.return_value = sample_user

        with patch(
            "app.services.user_service.upload_user_picture",
            new_callable=AsyncMock,
            side_effect=Exception("Upload failed"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_user_profile(sample_user.id, picture_data=b"fake_image")

            assert exc_info.value.status_code == 500

    async def test_raises_500_on_unexpected_error(self, mock_repo):
        mock_get, _ = mock_repo
        mock_get.side_effect = Exception("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="Test")

        assert exc_info.value.status_code == 500
