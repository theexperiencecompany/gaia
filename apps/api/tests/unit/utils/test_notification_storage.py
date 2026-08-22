"""Unit tests for MongoDBNotificationStorage and channel preferences.

Storage now delegates persistence to ``notification_repository`` (real DB
behaviour is covered by the NotificationRepository contract tests). These tests
mock the repository and assert the storage methods delegate correctly.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.utils.notification.channel_preferences import (
    fetch_channel_preferences,
    normalize_channel_preferences,
)
from app.utils.notification.storage import MongoDBNotificationStorage


@pytest.fixture
def mock_repo():
    with patch("app.utils.notification.storage.notification_repository") as repo:
        repo.create = AsyncMock()
        repo.get_for_user = AsyncMock()
        repo.update_fields = AsyncMock()
        repo.list_for_user = AsyncMock(return_value=[])
        repo.count_for_user = AsyncMock(return_value=0)
        yield repo


@pytest.fixture
def storage():
    return MongoDBNotificationStorage()


class TestNotificationStorageDelegation:
    async def test_save_delegates_to_create(self, storage, mock_repo):
        record = object()
        await storage.save_notification(record)  # type: ignore[arg-type]
        mock_repo.create.assert_awaited_once_with(record)

    async def test_get_delegates_with_user(self, storage, mock_repo):
        sentinel = object()
        mock_repo.get_for_user.return_value = sentinel
        result = await storage.get_notification("notif-1", "user-1")
        assert result is sentinel
        mock_repo.get_for_user.assert_awaited_once_with("notif-1", "user-1")

    async def test_get_delegates_without_user(self, storage, mock_repo):
        await storage.get_notification("notif-1", None)
        mock_repo.get_for_user.assert_awaited_once_with("notif-1", None)

    async def test_update_delegates_free_form_fields(self, storage, mock_repo):
        await storage.update_notification(
            "notif-1", {"status": "read", "read_at": "2024-01-01T00:00:00Z"}
        )
        mock_repo.update_fields.assert_awaited_once_with(
            "notif-1", status="read", read_at="2024-01-01T00:00:00Z"
        )

    async def test_list_forwards_all_filters(self, storage, mock_repo):
        await storage.get_user_notifications(
            "user-1",
            status=NotificationStatus.READ,
            limit=10,
            offset=5,
            channel_type="in_app",
            notification_type=NotificationType.INFO,
            source=NotificationSourceEnum.AI_AGENT,
        )
        mock_repo.list_for_user.assert_awaited_once_with(
            "user-1",
            status=NotificationStatus.READ,
            channel_type="in_app",
            notification_type=NotificationType.INFO,
            source=NotificationSourceEnum.AI_AGENT,
            limit=10,
            offset=5,
        )

    async def test_count_forwards_filters(self, storage, mock_repo):
        mock_repo.count_for_user.return_value = 7
        result = await storage.get_notification_count(
            "user-1", status=NotificationStatus.PENDING, channel_type="in_app"
        )
        assert result == 7
        mock_repo.count_for_user.assert_awaited_once_with(
            "user-1", status=NotificationStatus.PENDING, channel_type="in_app"
        )


# ---------------------------------------------------------------------------
# normalize_channel_preferences
# ---------------------------------------------------------------------------


class TestNormalizeChannelPreferences:
    """Tests for normalize_channel_preferences."""

    def test_none_input_uses_defaults(self) -> None:
        """None prefs fallback to DEFAULT_CHANNEL_PREFERENCES values."""
        result = normalize_channel_preferences(None)
        assert result == {
            "telegram": True,
            "discord": True,
            "whatsapp": True,
            "slack": True,
            "imessage": True,
            "email": True,
        }

    def test_empty_dict_uses_defaults(self) -> None:
        """Empty dict falls back to defaults for every channel."""
        result = normalize_channel_preferences({})
        assert result == {
            "telegram": True,
            "discord": True,
            "whatsapp": True,
            "slack": True,
            "imessage": True,
            "email": True,
        }

    def test_explicit_false_overrides_default(self) -> None:
        """An explicitly False value overrides the default True."""
        result = normalize_channel_preferences({"telegram": False, "discord": True})
        assert result["telegram"] is False
        assert result["discord"] is True

    def test_email_false_respected(self) -> None:
        """An explicitly False email preference is respected (unsubscribe)."""
        result = normalize_channel_preferences({"email": False})
        assert result["email"] is False

    def test_truthy_values_coerced_to_bool(self) -> None:
        """Non-boolean truthy values are coerced to True."""
        result = normalize_channel_preferences({"telegram": 1, "discord": "yes"})
        assert result["telegram"] is True
        assert result["discord"] is True

    def test_falsy_values_coerced_to_bool(self) -> None:
        """Non-boolean falsy values are coerced to False."""
        result = normalize_channel_preferences({"telegram": 0, "discord": ""})
        assert result["telegram"] is False
        assert result["discord"] is False

    def test_extra_keys_ignored(self) -> None:
        """Keys not in DEFAULT_CHANNEL_PREFERENCES are not in the result."""
        result = normalize_channel_preferences({"telegram": True, "discord": True, "sms": True})
        assert "sms" not in result

    def test_partial_prefs_fill_missing_with_defaults(self) -> None:
        """When only some channels are provided, missing ones use defaults."""
        result = normalize_channel_preferences({"telegram": False})
        assert result["telegram"] is False
        assert result["discord"] is True  # default


# ---------------------------------------------------------------------------
# fetch_channel_preferences
# ---------------------------------------------------------------------------


class TestFetchChannelPreferences:
    """Tests for fetch_channel_preferences (async DB call)."""

    async def test_user_found_with_prefs(self) -> None:
        """Returns normalized prefs from the user document."""
        user = SimpleNamespace(notification_channel_prefs={"telegram": False, "discord": True})
        with patch(
            "app.utils.notification.channel_preferences.user_repository.get",
            new_callable=AsyncMock,
            return_value=user,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {
            "telegram": False,
            "discord": True,
            "whatsapp": True,
            "slack": True,
            "imessage": True,
            "email": True,
        }

    async def test_user_not_found(self) -> None:
        """When user doc is None, use defaults (None prefs)."""
        with patch(
            "app.utils.notification.channel_preferences.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {
            "telegram": True,
            "discord": True,
            "whatsapp": True,
            "slack": True,
            "imessage": True,
            "email": True,
        }

    async def test_user_with_null_prefs_field(self) -> None:
        """When notification_channel_prefs is explicitly None, use defaults."""
        user = SimpleNamespace(notification_channel_prefs=None)
        with patch(
            "app.utils.notification.channel_preferences.user_repository.get",
            new_callable=AsyncMock,
            return_value=user,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {
            "telegram": True,
            "discord": True,
            "whatsapp": True,
            "slack": True,
            "imessage": True,
            "email": True,
        }
