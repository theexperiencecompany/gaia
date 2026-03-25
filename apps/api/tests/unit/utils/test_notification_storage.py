"""Unit tests for notification storage and channel preferences."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.utils.notification.channel_preferences import (
    fetch_channel_preferences,
    normalize_channel_preferences,
)
from app.utils.notification.storage import MongoDBNotificationStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    user_id: str = "user-1",
    notification_id: str = "notif-1",
    source: NotificationSourceEnum = NotificationSourceEnum.AI_TODO_ADDED,
    ntype: NotificationType = NotificationType.INFO,
) -> NotificationRequest:
    return NotificationRequest(
        id=notification_id,
        user_id=user_id,
        source=source,
        type=ntype,
        priority=2,
        channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
        content=NotificationContent(title="Title", body="Body"),
        metadata={},
    )


def _make_record(
    request: Optional[NotificationRequest] = None,
    status: NotificationStatus = NotificationStatus.PENDING,
) -> NotificationRecord:
    req = request or _make_request()
    return NotificationRecord(
        id=req.id,
        user_id=req.user_id,
        status=status,
        created_at=req.created_at,
        original_request=req,
    )


def _record_to_dict(record: NotificationRecord) -> Dict[str, Any]:
    """Simulate what MongoDB would return by round-tripping through model_dump."""
    return record.model_dump()


# ---------------------------------------------------------------------------
# MongoDBNotificationStorage.save_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSaveNotification:
    """Tests for MongoDBNotificationStorage.save_notification."""

    async def test_save_inserts_document(self) -> None:
        """save_notification calls insert_one with the model dump."""
        mock_collection = AsyncMock()

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            record = _make_record()
            await storage.save_notification(record)

        mock_collection.insert_one.assert_awaited_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["id"] == record.id
        assert doc["user_id"] == record.user_id


# ---------------------------------------------------------------------------
# MongoDBNotificationStorage.get_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNotification:
    """Tests for MongoDBNotificationStorage.get_notification."""

    async def test_get_notification_found_with_user_id(self) -> None:
        """Returns a NotificationRecord when the document exists."""
        record = _make_record()
        raw_doc = _record_to_dict(record)
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = raw_doc

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            result = await storage.get_notification("notif-1", "user-1")

        assert result is not None
        assert result.id == "notif-1"
        assert result.user_id == "user-1"
        mock_collection.find_one.assert_awaited_once_with(
            {"id": "notif-1", "user_id": "user-1"}
        )

    async def test_get_notification_found_without_user_id(self) -> None:
        """When user_id is None, query does not include user_id."""
        record = _make_record()
        raw_doc = _record_to_dict(record)
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = raw_doc

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            result = await storage.get_notification("notif-1", None)

        assert result is not None
        mock_collection.find_one.assert_awaited_once_with({"id": "notif-1"})

    async def test_get_notification_not_found(self) -> None:
        """Returns None when find_one returns None."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = None

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            result = await storage.get_notification("notif-missing", "user-1")

        assert result is None


# ---------------------------------------------------------------------------
# MongoDBNotificationStorage.update_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateNotification:
    """Tests for MongoDBNotificationStorage.update_notification."""

    async def test_update_adds_updated_at(self) -> None:
        """update_notification injects updated_at into the $set payload."""
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1

        mock_collection = AsyncMock()
        mock_collection.update_one.return_value = mock_result

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            updates: Dict[str, Any] = {"status": "read"}
            await storage.update_notification("notif-1", updates)

        mock_collection.update_one.assert_awaited_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"id": "notif-1"}
        set_payload = call_args[0][1]["$set"]
        assert "updated_at" in set_payload
        assert set_payload["status"] == "read"

    async def test_update_no_match_logs_warning(self) -> None:
        """When matched_count == 0, a warning is logged (no exception)."""
        mock_result = MagicMock()
        mock_result.matched_count = 0
        mock_result.modified_count = 0

        mock_collection = AsyncMock()
        mock_collection.update_one.return_value = mock_result

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            # Should not raise
            await storage.update_notification("notif-nonexistent", {"status": "read"})

        mock_collection.update_one.assert_awaited_once()

    async def test_update_matched_but_not_modified(self) -> None:
        """When matched but not modified (same value), no error raised."""
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_result.modified_count = 0

        mock_collection = AsyncMock()
        mock_collection.update_one.return_value = mock_result

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.update_notification("notif-1", {"status": "read"})

        # Just verifies no exception is raised
        mock_collection.update_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# MongoDBNotificationStorage.get_user_notifications
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserNotifications:
    """Tests for MongoDBNotificationStorage.get_user_notifications."""

    def _mock_cursor(self, results: List[Dict[str, Any]]) -> MagicMock:
        """Build a mock Motor cursor that supports chaining + to_list."""
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=results)
        return cursor

    async def test_basic_user_query(self) -> None:
        """Minimal query includes only user_id."""
        record = _make_record()
        raw = _record_to_dict(record)
        mock_collection = MagicMock()
        cursor = self._mock_cursor([raw])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            results = await storage.get_user_notifications("user-1")

        mock_collection.find.assert_called_once_with({"user_id": "user-1"})
        assert len(results) == 1
        assert results[0].id == record.id

    async def test_filter_by_status(self) -> None:
        """Status filter is added to the query."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications(
                "user-1", status=NotificationStatus.DELIVERED
            )

        query = mock_collection.find.call_args[0][0]
        assert query["status"] == NotificationStatus.DELIVERED

    async def test_filter_by_channel_type(self) -> None:
        """Channel type filter is added to the query."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications("user-1", channel_type="telegram")

        query = mock_collection.find.call_args[0][0]
        assert query["channels.channel_type"] == "telegram"

    async def test_filter_by_notification_type(self) -> None:
        """Notification type filter uses dot notation into original_request."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications(
                "user-1", notification_type=NotificationType.WARNING
            )

        query = mock_collection.find.call_args[0][0]
        assert query["original_request.type"] == "warning"

    async def test_filter_by_source(self) -> None:
        """Source filter uses dot notation into original_request."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications(
                "user-1", source=NotificationSourceEnum.AI_REMINDER
            )

        query = mock_collection.find.call_args[0][0]
        assert query["original_request.source"] == "ai_reminder"

    async def test_pagination_limit_and_offset(self) -> None:
        """Limit and offset are forwarded to the cursor chain."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications("user-1", limit=10, offset=20)

        cursor.sort.assert_called_once_with("created_at", -1)
        cursor.skip.assert_called_once_with(20)
        cursor.limit.assert_called_once_with(10)
        cursor.to_list.assert_awaited_once_with(length=10)

    async def test_all_filters_combined(self) -> None:
        """All filters can be combined in a single query."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            await storage.get_user_notifications(
                "user-1",
                status=NotificationStatus.READ,
                limit=5,
                offset=10,
                channel_type="discord",
                notification_type=NotificationType.ERROR,
                source=NotificationSourceEnum.WORKFLOW_FAILED,
            )

        query = mock_collection.find.call_args[0][0]
        assert query["user_id"] == "user-1"
        assert query["status"] == NotificationStatus.READ
        assert query["channels.channel_type"] == "discord"
        assert query["original_request.type"] == "error"
        assert query["original_request.source"] == "workflow_failed"

    async def test_empty_results(self) -> None:
        """Returns empty list when no documents match."""
        mock_collection = MagicMock()
        cursor = self._mock_cursor([])
        mock_collection.find.return_value = cursor

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            results = await storage.get_user_notifications("user-1")

        assert results == []


# ---------------------------------------------------------------------------
# MongoDBNotificationStorage.get_notification_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNotificationCount:
    """Tests for MongoDBNotificationStorage.get_notification_count."""

    async def test_basic_count(self) -> None:
        """Counts documents for user with no extra filters."""
        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 42

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            count = await storage.get_notification_count("user-1")

        assert count == 42
        mock_collection.count_documents.assert_awaited_once_with({"user_id": "user-1"})

    async def test_count_with_status_filter(self) -> None:
        """Status filter is included in the count query."""
        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 5

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            count = await storage.get_notification_count(
                "user-1", status=NotificationStatus.DELIVERED
            )

        assert count == 5
        query = mock_collection.count_documents.call_args[0][0]
        assert query["status"] == NotificationStatus.DELIVERED

    async def test_count_with_channel_type_filter(self) -> None:
        """Channel type filter is included in the count query."""
        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 3

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            count = await storage.get_notification_count(
                "user-1", channel_type="telegram"
            )

        assert count == 3
        query = mock_collection.count_documents.call_args[0][0]
        assert query["channels.channel_type"] == "telegram"

    async def test_count_with_all_filters(self) -> None:
        """Both status and channel_type filters combined."""
        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 1

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            count = await storage.get_notification_count(
                "user-1",
                status=NotificationStatus.READ,
                channel_type="inapp",
            )

        assert count == 1
        query = mock_collection.count_documents.call_args[0][0]
        assert query["user_id"] == "user-1"
        assert query["status"] == NotificationStatus.READ
        assert query["channels.channel_type"] == "inapp"

    async def test_count_zero(self) -> None:
        """Returns 0 when no documents match."""
        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 0

        with patch(
            "app.utils.notification.storage.notifications_collection",
            mock_collection,
        ):
            storage = MongoDBNotificationStorage()
            count = await storage.get_notification_count("user-empty")

        assert count == 0


# ---------------------------------------------------------------------------
# normalize_channel_preferences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeChannelPreferences:
    """Tests for normalize_channel_preferences."""

    def test_none_input_uses_defaults(self) -> None:
        """None prefs fallback to DEFAULT_CHANNEL_PREFERENCES values."""
        result = normalize_channel_preferences(None)
        assert result == {"telegram": True, "discord": True}

    def test_empty_dict_uses_defaults(self) -> None:
        """Empty dict falls back to defaults for every channel."""
        result = normalize_channel_preferences({})
        assert result == {"telegram": True, "discord": True}

    def test_explicit_false_overrides_default(self) -> None:
        """An explicitly False value overrides the default True."""
        result = normalize_channel_preferences({"telegram": False, "discord": True})
        assert result["telegram"] is False
        assert result["discord"] is True

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
        result = normalize_channel_preferences(
            {"telegram": True, "discord": True, "sms": True}
        )
        assert "sms" not in result

    def test_partial_prefs_fill_missing_with_defaults(self) -> None:
        """When only some channels are provided, missing ones use defaults."""
        result = normalize_channel_preferences({"telegram": False})
        assert result["telegram"] is False
        assert result["discord"] is True  # default


# ---------------------------------------------------------------------------
# fetch_channel_preferences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchChannelPreferences:
    """Tests for fetch_channel_preferences (async DB call)."""

    async def test_user_found_with_prefs(self) -> None:
        """Returns normalized prefs from the user document."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = {
            "_id": "fake-object-id",
            "notification_channel_prefs": {"telegram": False, "discord": True},
        }

        with patch(
            "app.utils.notification.channel_preferences.users_collection",
            mock_collection,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result["telegram"] is False
        assert result["discord"] is True

    async def test_user_found_without_prefs(self) -> None:
        """When user exists but has no notification_channel_prefs, use defaults."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = {"_id": "fake-object-id"}

        with patch(
            "app.utils.notification.channel_preferences.users_collection",
            mock_collection,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {"telegram": True, "discord": True}

    async def test_user_not_found(self) -> None:
        """When user doc is None, use defaults (None prefs)."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = None

        with patch(
            "app.utils.notification.channel_preferences.users_collection",
            mock_collection,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {"telegram": True, "discord": True}

    async def test_user_with_null_prefs_field(self) -> None:
        """When notification_channel_prefs is explicitly None, use defaults."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = {
            "_id": "fake-object-id",
            "notification_channel_prefs": None,
        }

        with patch(
            "app.utils.notification.channel_preferences.users_collection",
            mock_collection,
        ):
            result = await fetch_channel_preferences("507f1f77bcf86cd799439011")

        assert result == {"telegram": True, "discord": True}
