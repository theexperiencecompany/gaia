"""Unit tests for the notification service facade.

NotificationService is a thin facade over NotificationOrchestrator — these
tests lock that every public method delegates to the orchestrator and passes
the caller's arguments through unchanged (including the None-vs-value
distinctions that matter at the API boundary).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification.notification_models import (
    ActionResult,
    BulkActions,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.models.notification.request_models import NotificationQuery
from app.services.notification_service import NotificationService, notification_service

_MOD = "app.services.notification_service"


@pytest.fixture
def service():
    with patch(f"{_MOD}.NotificationOrchestrator") as m_orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.create_notification = AsyncMock()
        orchestrator.execute_action = AsyncMock()
        orchestrator.mark_as_read = AsyncMock()
        orchestrator.get_user_notifications = AsyncMock()
        orchestrator.get_notification = AsyncMock()
        orchestrator.bulk_actions = AsyncMock()
        orchestrator.storage = MagicMock()
        orchestrator.storage.get_notification_count = AsyncMock()
        orchestrator.register_channel_adapter = MagicMock()
        orchestrator.register_action_handler = MagicMock()
        m_orchestrator_cls.return_value = orchestrator
        yield NotificationService(), orchestrator


class TestNotificationService:
    async def test_create_notification_delegates(self, service):
        svc, orchestrator = service
        request = MagicMock()
        orchestrator.create_notification.return_value = None

        assert await svc.create_notification(request) is None
        orchestrator.create_notification.assert_awaited_once_with(request)

    async def test_execute_action_delegates_with_request(self, service):
        svc, orchestrator = service
        result = ActionResult(success=True)
        orchestrator.execute_action.return_value = result
        request = MagicMock()

        got = await svc.execute_action("notif-1", "action-1", "user-1", request)

        assert got is result
        orchestrator.execute_action.assert_awaited_once_with(
            "notif-1", "action-1", "user-1", request=request
        )

    async def test_execute_action_without_request(self, service):
        svc, orchestrator = service
        orchestrator.execute_action.return_value = ActionResult(success=False)

        await svc.execute_action("notif-1", "action-1", "user-1", None)

        orchestrator.execute_action.assert_awaited_once_with(
            "notif-1", "action-1", "user-1", request=None
        )

    async def test_mark_as_read_delegates(self, service):
        svc, orchestrator = service
        orchestrator.mark_as_read.return_value = None

        assert await svc.mark_as_read("notif-1", "user-1") is None
        orchestrator.mark_as_read.assert_awaited_once_with("notif-1", "user-1")

    async def test_get_user_notifications_passes_filters(self, service):
        svc, orchestrator = service
        orchestrator.get_user_notifications.return_value = []

        query = NotificationQuery(
            status=NotificationStatus.READ,
            limit=10,
            offset=5,
            channel_type="in_app",
            notification_type=NotificationType.WARNING,
            source="ai_agent",
        )

        await svc.get_user_notifications("user-1", query)

        orchestrator.get_user_notifications.assert_awaited_once_with("user-1", query)

    async def test_get_notification_delegates(self, service):
        svc, orchestrator = service
        view = MagicMock(spec=NotificationView)
        orchestrator.get_notification.return_value = view

        assert await svc.get_notification("notif-1", "user-1") is view
        orchestrator.get_notification.assert_awaited_once_with(
            notification_id="notif-1", user_id="user-1"
        )

    async def test_get_notification_count_delegates_to_storage(self, service):
        svc, orchestrator = service
        orchestrator.storage.get_notification_count.return_value = 7

        count = await svc.get_user_notifications_count(
            "user-1", NotificationStatus.PENDING, "in_app"
        )

        assert count == 7
        orchestrator.storage.get_notification_count.assert_awaited_once_with(
            "user-1", NotificationStatus.PENDING, "in_app"
        )

    async def test_bulk_actions_delegates(self, service):
        svc, orchestrator = service
        orchestrator.bulk_actions.return_value = {"notif-1": True}

        result = await svc.bulk_actions(["notif-1"], "user-1", BulkActions.MARK_READ)

        assert result == {"notif-1": True}
        orchestrator.bulk_actions.assert_awaited_once_with(
            ["notif-1"], "user-1", BulkActions.MARK_READ
        )

    def test_register_channel_adapter_delegates(self, service):
        svc, orchestrator = service
        adapter = MagicMock()

        svc.register_channel_adapter(adapter)

        orchestrator.register_channel_adapter.assert_called_once_with(adapter)

    def test_register_action_handler_delegates(self, service):
        svc, orchestrator = service
        handler = MagicMock()

        svc.register_action_handler(handler)

        orchestrator.register_action_handler.assert_called_once_with(handler)


class TestGlobalInstance:
    def test_module_singleton_is_a_notification_service(self):
        assert isinstance(notification_service, NotificationService)
