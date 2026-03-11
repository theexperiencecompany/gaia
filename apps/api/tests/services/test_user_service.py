"""
Tests for user_service.py — user lookup and profile update logic.

Mocks at the MongoDB collection boundary.
"""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

COLLECTION = "app.services.user_service.users_collection"
FAKE_OID = ObjectId("507f1f77bcf86cd799439011")


class TestGetUserById:
    async def test_returns_user_with_string_id(self):
        from app.services.user_service import get_user_by_id

        fake_doc = {
            "_id": FAKE_OID,
            "name": "Test User",
            "email": "test@example.com",
        }
        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            result = await get_user_by_id(str(FAKE_OID))

        assert result["_id"] == str(FAKE_OID)
        assert result["name"] == "Test User"

    async def test_returns_none_when_not_found(self):
        from app.services.user_service import get_user_by_id

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            result = await get_user_by_id(str(FAKE_OID))

        assert result is None

    async def test_raises_404_on_db_error(self):
        from app.services.user_service import get_user_by_id

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(side_effect=Exception("DB error"))
            with pytest.raises(HTTPException) as exc:
                await get_user_by_id(str(FAKE_OID))
            assert exc.value.status_code == 404


class TestGetUserByEmail:
    async def test_returns_user(self):
        from app.services.user_service import get_user_by_email

        fake_doc = {
            "_id": FAKE_OID,
            "name": "Test User",
            "email": "test@example.com",
        }
        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            result = await get_user_by_email("test@example.com")

        assert result["email"] == "test@example.com"
        assert isinstance(result["_id"], str)

    async def test_returns_none_when_not_found(self):
        from app.services.user_service import get_user_by_email

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            result = await get_user_by_email("missing@example.com")

        assert result is None


class TestUpdateUserProfile:
    async def test_update_name_only(self):
        from app.services.user_service import update_user_profile

        fake_doc = {
            "_id": FAKE_OID,
            "name": "Old Name",
            "email": "test@example.com",
        }
        updated_doc = {
            "_id": str(FAKE_OID),
            "name": "New Name",
            "email": "test@example.com",
        }

        with (
            patch(COLLECTION) as mock_col,
            patch(
                "app.services.user_service.get_user_by_id",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            mock_col.update_one = AsyncMock()

            result = await update_user_profile(str(FAKE_OID), name="New Name")

        assert result["name"] == "New Name"

        # Verify the $set passed to update_one contained the name
        update_call = mock_col.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["name"] == "New Name"
        assert "updated_at" in set_data

    async def test_strips_whitespace_from_name(self):
        from app.services.user_service import update_user_profile

        fake_doc = {"_id": FAKE_OID, "name": "Old", "email": "t@t.com"}
        updated_doc = {"_id": str(FAKE_OID), "name": "Trimmed", "email": "t@t.com"}

        with (
            patch(COLLECTION) as mock_col,
            patch(
                "app.services.user_service.get_user_by_id",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            mock_col.update_one = AsyncMock()

            await update_user_profile(str(FAKE_OID), name="  Trimmed  ")

        set_data = mock_col.update_one.call_args[0][1]["$set"]
        assert set_data["name"] == "Trimmed"

    async def test_skips_empty_name(self):
        from app.services.user_service import update_user_profile

        fake_doc = {"_id": FAKE_OID, "name": "Keep", "email": "t@t.com"}
        updated_doc = {"_id": str(FAKE_OID), "name": "Keep", "email": "t@t.com"}

        with (
            patch(COLLECTION) as mock_col,
            patch(
                "app.services.user_service.get_user_by_id",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            mock_col.update_one = AsyncMock()

            await update_user_profile(str(FAKE_OID), name="   ")

        set_data = mock_col.update_one.call_args[0][1]["$set"]
        assert "name" not in set_data  # Empty name should not be set

    async def test_raises_404_when_user_not_found(self):
        from app.services.user_service import update_user_profile

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await update_user_profile(str(FAKE_OID), name="New")
            assert exc.value.status_code == 404

    async def test_upload_picture_failure_raises_500(self):
        from app.services.user_service import update_user_profile

        fake_doc = {"_id": FAKE_OID, "name": "User", "email": "t@t.com"}

        with (
            patch(COLLECTION) as mock_col,
            patch(
                "app.services.user_service.upload_user_picture",
                new_callable=AsyncMock,
                side_effect=Exception("Cloudinary down"),
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            with pytest.raises(HTTPException) as exc:
                await update_user_profile(
                    str(FAKE_OID), picture_data=b"fake_image_data"
                )
            assert exc.value.status_code == 500
