"""Unit tests for the device token service functions.

The repository singleton is patched where the service imports it; what the
repository does with Mongo is proven in tests/contracts/test_device_tokens_repository.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.device_token_models import DeviceTokenDocument, PlatformType
from app.services import device_token_service
from tests.helpers import captured_wide_event

USER_ID = "507f1f77bcf86cd799439011"
TOKEN = "ExponentPushToken[abc]"


@pytest.fixture
def mock_repo():
    with patch("app.services.device_token_service.device_token_repository") as repo:
        repo.register = AsyncMock(return_value=True)
        repo.count_for_user = AsyncMock(return_value=0)
        repo.get = AsyncMock(return_value=None)
        repo.delete = AsyncMock(return_value=False)
        yield repo


def _held_token() -> DeviceTokenDocument:
    return DeviceTokenDocument.model_validate(
        {
            "user_id": USER_ID,
            "token": TOKEN,
            "platform": "ios",
            "is_active": True,
            "created_at": "2026-01-11T10:00:00Z",
            "updated_at": "2026-01-11T10:00:00Z",
        }
    )


@pytest.mark.unit
class TestRegisterDeviceToken:
    async def test_a_new_token_is_registered_and_logged_as_registered(self, mock_repo):
        async with captured_wide_event() as event:
            result = await device_token_service.register_device_token(
                USER_ID, TOKEN, PlatformType.IOS, device_id="device123"
            )

        assert result is True
        mock_repo.register.assert_awaited_once_with(
            user_id=USER_ID, token=TOKEN, platform=PlatformType.IOS, device_id="device123"
        )
        assert event["device_token"] == {
            "user_id": USER_ID,
            "platform": "ios",
            "action": "registered",
        }

    async def test_a_known_token_is_logged_as_updated(self, mock_repo):
        mock_repo.register.return_value = False

        async with captured_wide_event() as event:
            result = await device_token_service.register_device_token(
                USER_ID, TOKEN, PlatformType.ANDROID
            )

        assert result is True
        mock_repo.register.assert_awaited_once_with(
            user_id=USER_ID, token=TOKEN, platform=PlatformType.ANDROID, device_id=None
        )
        assert event["device_token"] == {
            "user_id": USER_ID,
            "platform": "android",
            "action": "updated",
        }

    async def test_a_repository_failure_returns_false_and_is_reported(self, mock_repo):
        mock_repo.register.side_effect = RuntimeError("DB error")

        async with captured_wide_event() as event:
            result = await device_token_service.register_device_token(
                USER_ID, TOKEN, PlatformType.IOS, device_id="device123"
            )

        assert result is False
        (error,) = event["errors"]
        assert error["msg"].endswith("Failed to register device token")
        assert (error["error_type"], error["user_id"]) == ("RuntimeError", USER_ID)
        assert error["device_id"] == "device123"
        assert "device_token" not in event


@pytest.mark.unit
class TestGetUserDeviceCount:
    async def test_returns_the_users_count(self, mock_repo):
        mock_repo.count_for_user.return_value = 3

        assert await device_token_service.get_user_device_count(USER_ID) == 3
        mock_repo.count_for_user.assert_awaited_once_with(USER_ID)

    async def test_a_repository_failure_returns_zero_and_is_reported(self, mock_repo):
        mock_repo.count_for_user.side_effect = RuntimeError("DB error")

        async with captured_wide_event() as event:
            result = await device_token_service.get_user_device_count(USER_ID)

        assert result == 0
        (error,) = event["errors"]
        assert error["msg"].endswith("Failed to get device count")
        assert (error["error_type"], error["user_id"]) == ("RuntimeError", USER_ID)


@pytest.mark.unit
class TestVerifyTokenOwnership:
    async def test_true_when_the_user_holds_the_token(self, mock_repo):
        mock_repo.get.return_value = _held_token()

        assert await device_token_service.verify_token_ownership(TOKEN, USER_ID) is True
        mock_repo.get.assert_awaited_once_with(TOKEN, user_id=USER_ID)

    async def test_false_when_the_user_does_not_hold_the_token(self, mock_repo):
        assert await device_token_service.verify_token_ownership(TOKEN, USER_ID) is False
        mock_repo.get.assert_awaited_once_with(TOKEN, user_id=USER_ID)

    async def test_a_repository_failure_returns_false_and_is_reported(self, mock_repo):
        mock_repo.get.side_effect = RuntimeError("DB error")

        async with captured_wide_event() as event:
            result = await device_token_service.verify_token_ownership(TOKEN, USER_ID)

        assert result is False
        (error,) = event["errors"]
        assert error["msg"].endswith("Failed to verify token ownership")
        assert (error["error_type"], error["user_id"]) == ("RuntimeError", USER_ID)


@pytest.mark.unit
class TestUnregisterDeviceToken:
    async def test_a_held_token_is_deleted_and_logged_as_unregistered(self, mock_repo):
        mock_repo.delete.return_value = True

        async with captured_wide_event() as event:
            result = await device_token_service.unregister_device_token(TOKEN, USER_ID)

        assert result is True
        mock_repo.delete.assert_awaited_once_with(TOKEN, user_id=USER_ID)
        assert event["device_token"] == {"user_id": USER_ID, "action": "unregistered"}
        assert "warnings" not in event

    async def test_a_token_the_user_does_not_hold_returns_false_with_a_warning(self, mock_repo):
        async with captured_wide_event() as event:
            result = await device_token_service.unregister_device_token(TOKEN, USER_ID)

        assert result is False
        mock_repo.delete.assert_awaited_once_with(TOKEN, user_id=USER_ID)
        (warning,) = event["warnings"]
        assert warning["msg"].endswith("Device token not found or not owned by user")
        assert warning["user_id"] == USER_ID
        assert "device_token" not in event

    async def test_a_repository_failure_returns_false_and_is_reported(self, mock_repo):
        mock_repo.delete.side_effect = RuntimeError("DB error")

        async with captured_wide_event() as event:
            result = await device_token_service.unregister_device_token(TOKEN, USER_ID)

        assert result is False
        (error,) = event["errors"]
        assert error["msg"].endswith("Failed to unregister device token")
        assert (error["error_type"], error["user_id"]) == ("RuntimeError", USER_ID)
