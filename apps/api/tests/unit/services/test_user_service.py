"""Unit tests for user service operations."""

import pytest
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.services.user_service import (
    get_user_by_email,
    get_user_by_id,
    update_user_profile,
)


@pytest.fixture
def mock_users_collection():
    with patch("app.services.user_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def sample_user_doc():
    oid = ObjectId()
    return {
        "_id": oid,
        "email": "alice@example.com",
        "name": "Alice",
        "picture": "https://example.com/alice.jpg",
        "selected_model": "gpt-4",
    }


@pytest.mark.unit
class TestGetUserById:
    async def test_returns_user_with_string_id(
        self, mock_users_collection, sample_user_doc
    ):
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)
        oid_str = str(sample_user_doc["_id"])

        result = await get_user_by_id(oid_str)

        assert result is not None
        assert result["_id"] == oid_str
        assert result["email"] == "alice@example.com"

    async def test_returns_none_when_not_found(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        oid_str = str(ObjectId())

        result = await get_user_by_id(oid_str)
        assert result is None

    async def test_raises_404_on_exception(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(HTTPException) as exc_info:
            await get_user_by_id("invalid_id")

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestGetUserByEmail:
    async def test_returns_user_with_string_id(
        self, mock_users_collection, sample_user_doc
    ):
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)

        result = await get_user_by_email("alice@example.com")

        assert result is not None
        assert isinstance(result["_id"], str)

    async def test_returns_none_when_not_found(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await get_user_by_email("nobody@example.com")
        assert result is None

    async def test_raises_404_on_exception(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(HTTPException) as exc_info:
            await get_user_by_email("bad@example.com")

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestUpdateUserProfile:
    async def test_updates_name(self, mock_users_collection, sample_user_doc):
        oid_str = str(sample_user_doc["_id"])
        updated_doc = {**sample_user_doc, "name": "Alice Updated", "_id": oid_str}

        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)
        mock_users_collection.update_one = AsyncMock()

        with patch(
            "app.services.user_service.get_user_by_id",
            new_callable=AsyncMock,
            return_value=updated_doc,
        ):
            result = await update_user_profile(oid_str, name="Alice Updated")

        assert result["name"] == "Alice Updated"
        assert result["user_id"] == oid_str

        update_call = mock_users_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["name"] == "Alice Updated"
        assert "updated_at" in set_data

    async def test_raises_404_when_user_not_found(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="New Name")

        assert exc_info.value.status_code == 404

    async def test_strips_whitespace_from_name(
        self, mock_users_collection, sample_user_doc
    ):
        oid_str = str(sample_user_doc["_id"])
        updated_doc = {**sample_user_doc, "name": "Trimmed", "_id": oid_str}

        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)
        mock_users_collection.update_one = AsyncMock()

        with patch(
            "app.services.user_service.get_user_by_id",
            new_callable=AsyncMock,
            return_value=updated_doc,
        ):
            await update_user_profile(oid_str, name="  Trimmed  ")

        update_call = mock_users_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["name"] == "Trimmed"

    async def test_skips_empty_name(self, mock_users_collection, sample_user_doc):
        oid_str = str(sample_user_doc["_id"])
        updated_doc = {**sample_user_doc, "_id": oid_str}

        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)
        mock_users_collection.update_one = AsyncMock()

        with patch(
            "app.services.user_service.get_user_by_id",
            new_callable=AsyncMock,
            return_value=updated_doc,
        ):
            await update_user_profile(oid_str, name="   ")

        update_call = mock_users_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert "name" not in set_data

    async def test_updates_with_extra_data(
        self, mock_users_collection, sample_user_doc
    ):
        oid_str = str(sample_user_doc["_id"])
        updated_doc = {
            **sample_user_doc,
            "_id": oid_str,
            "selected_model": "claude-3",
        }

        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)
        mock_users_collection.update_one = AsyncMock()

        with patch(
            "app.services.user_service.get_user_by_id",
            new_callable=AsyncMock,
            return_value=updated_doc,
        ):
            result = await update_user_profile(
                oid_str, data={"selected_model": "claude-3"}
            )

        assert result["selected_model"] == "claude-3"

    async def test_raises_500_on_picture_upload_failure(
        self, mock_users_collection, sample_user_doc
    ):
        oid_str = str(sample_user_doc["_id"])
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)

        with patch(
            "app.services.user_service.upload_user_picture",
            new_callable=AsyncMock,
            side_effect=Exception("Upload failed"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_user_profile(oid_str, picture_data=b"fake_image")

            assert exc_info.value.status_code == 500

    async def test_raises_500_on_unexpected_error(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(side_effect=Exception("Unexpected"))

        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(str(ObjectId()), name="Test")

        assert exc_info.value.status_code == 500
