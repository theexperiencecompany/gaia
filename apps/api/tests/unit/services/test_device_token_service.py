"""Unit tests for DeviceTokenService."""

from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.device_token_models import PlatformType
from app.services.device_token_service import DeviceTokenService


class _AsyncIterator:
    """Helper to create a proper async iterator from a list of items."""

    def __init__(self, items: List):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_collection():
    return AsyncMock()


@pytest.fixture
def service(mock_collection):
    mock_mongodb = MagicMock()
    mock_mongodb.database.get_collection.return_value = mock_collection
    svc = DeviceTokenService(mock_mongodb)
    svc.collection = mock_collection
    return svc


# ---------------------------------------------------------------------------
# register_device_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterDeviceToken:
    async def test_register_new_token(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=MagicMock(upserted_id="new_id")
        )

        result = await service.register_device_token(
            "user1", "ExponentPushToken[abc]", PlatformType.IOS
        )

        assert result is True
        mock_collection.update_one.assert_awaited_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"token": "ExponentPushToken[abc]"}
        set_data = call_args[0][1]["$set"]
        assert set_data["user_id"] == "user1"
        assert set_data["platform"] == "ios"
        assert set_data["is_active"] is True

    async def test_update_existing_token(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(return_value=MagicMock(upserted_id=None))

        result = await service.register_device_token(
            "user1", "ExponentPushToken[abc]", PlatformType.ANDROID
        )

        assert result is True

    async def test_register_with_device_id(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=MagicMock(upserted_id="new_id")
        )

        result = await service.register_device_token(
            "user1", "ExponentPushToken[abc]", PlatformType.IOS, device_id="device123"
        )

        assert result is True
        set_data = mock_collection.update_one.call_args[0][1]["$set"]
        assert set_data["device_id"] == "device123"

    async def test_register_failure_returns_false(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.register_device_token(
            "user1", "ExponentPushToken[abc]", PlatformType.IOS
        )

        assert result is False


# ---------------------------------------------------------------------------
# get_user_device_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserDeviceCount:
    async def test_returns_count(self, service, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=3)

        result = await service.get_user_device_count("user1")

        assert result == 3
        mock_collection.count_documents.assert_awaited_once_with({"user_id": "user1"})

    async def test_returns_zero_on_error(self, service, mock_collection):
        mock_collection.count_documents = AsyncMock(side_effect=Exception("DB error"))

        result = await service.get_user_device_count("user1")

        assert result == 0


# ---------------------------------------------------------------------------
# verify_token_ownership
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyTokenOwnership:
    async def test_returns_true_when_owned(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(
            return_value={"token": "tok", "user_id": "user1"}
        )

        result = await service.verify_token_ownership("tok", "user1")

        assert result is True

    async def test_returns_false_when_not_owned(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await service.verify_token_ownership("tok", "user1")

        assert result is False

    async def test_returns_false_on_error(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.verify_token_ownership("tok", "user1")

        assert result is False


# ---------------------------------------------------------------------------
# unregister_device_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnregisterDeviceToken:
    async def test_unregister_success(self, service, mock_collection):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        result = await service.unregister_device_token(
            "ExponentPushToken[abc]", "user1"
        )

        assert result is True
        mock_collection.delete_one.assert_awaited_once_with(
            {"token": "ExponentPushToken[abc]", "user_id": "user1"}
        )

    async def test_unregister_not_found(self, service, mock_collection):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await service.unregister_device_token("nonexistent", "user1")

        assert result is False

    async def test_unregister_error_returns_false(self, service, mock_collection):
        mock_collection.delete_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.unregister_device_token("tok", "user1")

        assert result is False

    async def test_token_masking_short_token(self, service, mock_collection):
        """Short tokens (<=24 chars) should be fully masked."""
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        # Should not raise with short token
        result = await service.unregister_device_token("short", "user1")
        assert result is True

    async def test_token_masking_long_token(self, service, mock_collection):
        """Long tokens (>24 chars) show first 20 and last 4 chars."""
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        long_token = "ExponentPushToken[abcdefghij123456789]"
        result = await service.unregister_device_token(long_token, "user1")
        assert result is True


# ---------------------------------------------------------------------------
# unregister_user_devices
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnregisterUserDevices:
    async def test_unregisters_all_devices(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=3))

        result = await service.unregister_user_devices("user1")

        assert result == 3
        mock_collection.delete_many.assert_awaited_once_with({"user_id": "user1"})

    async def test_returns_zero_when_no_devices(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await service.unregister_user_devices("user1")

        assert result == 0

    async def test_returns_zero_on_error(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(side_effect=Exception("DB error"))

        result = await service.unregister_user_devices("user1")

        assert result == 0


# ---------------------------------------------------------------------------
# get_user_tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserTokens:
    async def test_returns_active_tokens(self, service, mock_collection):
        docs = [
            {"token": "tok1"},
            {"token": "tok2"},
        ]
        mock_collection.find = MagicMock(return_value=_AsyncIterator(docs))

        result = await service.get_user_tokens("user1")

        assert result == ["tok1", "tok2"]
        mock_collection.find.assert_called_once_with(
            {"user_id": "user1", "is_active": True}
        )

    async def test_returns_all_tokens_when_not_active_only(
        self, service, mock_collection
    ):
        docs = [{"token": "tok1"}]
        mock_collection.find = MagicMock(return_value=_AsyncIterator(docs))

        result = await service.get_user_tokens("user1", active_only=False)

        assert result == ["tok1"]
        mock_collection.find.assert_called_once_with({"user_id": "user1"})

    async def test_returns_empty_on_error(self, service, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        result = await service.get_user_tokens("user1")

        assert result == []

    async def test_returns_empty_when_no_tokens(self, service, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncIterator([]))

        result = await service.get_user_tokens("user1")

        assert result == []


# ---------------------------------------------------------------------------
# deactivate_invalid_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivateInvalidToken:
    async def test_deactivates_token(self, service, mock_collection):
        mock_collection.update_one = AsyncMock()

        result = await service.deactivate_invalid_token("ExponentPushToken[abc]")

        assert result is True
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"token": "ExponentPushToken[abc]"}
        set_data = call_args[0][1]["$set"]
        assert set_data["is_active"] is False
        assert "updated_at" in set_data

    async def test_returns_false_on_error(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.deactivate_invalid_token("tok")

        assert result is False

    async def test_masking_short_token(self, service, mock_collection):
        """Short tokens get fully masked."""
        mock_collection.update_one = AsyncMock()

        result = await service.deactivate_invalid_token("short_tok")
        assert result is True

    async def test_masking_long_token(self, service, mock_collection):
        """Long tokens are partially masked in logs."""
        mock_collection.update_one = AsyncMock()

        long_token = "ExponentPushToken[abcdefghij123456789]"
        result = await service.deactivate_invalid_token(long_token)
        assert result is True


# ---------------------------------------------------------------------------
# get_device_token_service (module-level function)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDeviceTokenServiceFactory:
    def test_creates_service_on_first_call(self):
        with (
            patch(
                "app.services.device_token_service.device_token_service",
                None,
            ),
            patch(
                "app.db.mongodb.mongodb.init_mongodb",
                return_value=MagicMock(),
            ) as mock_init,
        ):
            from app.services.device_token_service import get_device_token_service

            svc = get_device_token_service()

            assert svc is not None
            mock_init.assert_called_once()
