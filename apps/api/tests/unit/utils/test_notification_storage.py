"""Unit tests for MongoDBNotificationStorage.

Storage now delegates persistence to ``notification_repository`` (real DB
behaviour is covered by the NotificationRepository contract tests). These tests
mock the repository and assert the storage methods delegate correctly.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
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


@pytest.mark.unit
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
