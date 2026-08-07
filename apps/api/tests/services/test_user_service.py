"""
Tests for user_service.py — user lookup and profile update logic.

Mocks at the user_repository boundary.
"""

from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.user_models import UserDocument

FAKE_OID = ObjectId("507f1f77bcf86cd799439011")
FAKE_ID = str(FAKE_OID)


def _user(**overrides: object) -> UserDocument:
    return UserDocument.model_validate(
        {"id": FAKE_ID, "name": "Test User", "email": "test@example.com", **overrides}
    )


class TestGetUserById:
    async def test_returns_user_with_string_id(self):
        from app.services.user_service import get_user_by_id

        with patch(
            "app.services.user_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=_user(),
        ):
            result = await get_user_by_id(FAKE_ID)

        assert result["_id"] == FAKE_ID
        assert result["name"] == "Test User"

    async def test_returns_none_when_not_found(self):
        from app.services.user_service import get_user_by_id

        with patch(
            "app.services.user_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_user_by_id(FAKE_ID)

        assert result is None

    async def test_raises_404_on_db_error(self):
        from app.services.user_service import get_user_by_id

        with patch(
            "app.services.user_service.user_repository.get",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_user_by_id(FAKE_ID)
            assert exc.value.status_code == 404


class TestUpdateUserProfile:
    async def test_update_name_only(self):
        from app.services.user_service import update_user_profile

        with (
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=_user(name="Old Name"),
            ),
            patch(
                "app.services.user_service.user_repository.update",
                new_callable=AsyncMock,
                return_value=_user(name="New Name"),
            ) as mock_update,
        ):
            result = await update_user_profile(FAKE_ID, name="New Name")

        assert result.name == "New Name"
        update_arg = mock_update.call_args.args[1]
        assert update_arg.model_dump(exclude_unset=True) == {"name": "New Name"}

    async def test_strips_whitespace_from_name(self):
        from app.services.user_service import update_user_profile

        with (
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=_user(name="Old"),
            ),
            patch(
                "app.services.user_service.user_repository.update",
                new_callable=AsyncMock,
                return_value=_user(name="Trimmed"),
            ) as mock_update,
        ):
            await update_user_profile(FAKE_ID, name="  Trimmed  ")

        assert mock_update.call_args.args[1].model_dump(exclude_unset=True)["name"] == "Trimmed"

    async def test_skips_empty_name(self):
        from app.services.user_service import update_user_profile

        with (
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=_user(name="Keep"),
            ),
            patch(
                "app.services.user_service.user_repository.update",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            await update_user_profile(FAKE_ID, name="   ")

        mock_update.assert_not_called()  # Empty name writes nothing

    async def test_raises_404_when_user_not_found(self):
        from app.services.user_service import update_user_profile

        with patch(
            "app.services.user_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc:
                await update_user_profile(FAKE_ID, name="New")
            assert exc.value.status_code == 404

    async def test_upload_picture_failure_raises_500(self):
        from app.services.user_service import update_user_profile

        with (
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=_user(),
            ),
            patch(
                "app.services.user_service.upload_user_picture",
                new_callable=AsyncMock,
                side_effect=Exception("Cloudinary down"),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await update_user_profile(FAKE_ID, picture_data=b"fake_image_data")
            assert exc.value.status_code == 500
