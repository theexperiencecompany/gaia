"""Unit tests for notification API endpoints.

Tests the notification endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationContentView,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.services.analytics_service import AnalyticsEvents

NOTIF_BASE = "/api/v1/notifications"
ANALYTICS_PATCH = "app.api.v1.endpoints.notification.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


FAKE_USER_ID = "507f1f77bcf86cd799439011"


def _make_view(notification_id: str = "n1", title: str = "Hello") -> NotificationView:
    """The flattened shape ``get_user_notifications`` / ``get_notification`` return."""
    return NotificationView(
        id=notification_id,
        user_id=FAKE_USER_ID,
        status=NotificationStatus.DELIVERED,
        created_at="2026-01-01T00:00:00+00:00",
        content=NotificationContentView(title=title, body="Body"),
        source=NotificationSourceEnum.AI_AGENT,
        type=NotificationType.INFO,
    )


def _make_record(
    notification_id: str = "n1", status: NotificationStatus = NotificationStatus.READ
) -> NotificationRecord:
    """The stored record ``mark_as_read`` returns (not the flattened view)."""
    return NotificationRecord(
        id=notification_id,
        user_id=FAKE_USER_ID,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        original_request=NotificationRequest(
            user_id=FAKE_USER_ID,
            source=NotificationSourceEnum.AI_AGENT,
            type=NotificationType.INFO,
            content=NotificationContent(title="Hello", body="Body"),
        ),
    )


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------


from app.models.notification.notification_models import NotificationListFilters, NotificationStatus
from tests.conftest import FAKE_USER


class TestGetNotifications:
    """GET /api/v1/notifications"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications_count",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications",
        new_callable=AsyncMock,
    )
    async def test_get_notifications_success(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
    ):
        mock_get.return_value = [_make_view()]
        mock_count.return_value = 1
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["id"] == "n1"
        assert data["notifications"][0]["content"]["title"] == "Hello"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications_count",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications",
        new_callable=AsyncMock,
    )
    async def test_get_notifications_with_status_filter(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
    ):
        mock_get.return_value = []
        mock_count.return_value = 0
        response = await client.get(f"{NOTIF_BASE}?status=read&channel_type=inapp&limit=7&offset=3")
        assert response.status_code == 200
        # The whole query string reaches the service as one query object.
        mock_get.assert_awaited_once_with(
            FAKE_USER["user_id"],
            filters=NotificationListFilters(
                status=NotificationStatus.READ, channel_type="inapp", limit=7, offset=3
            ),
        )
        data = response.json()
        assert data["total"] == 0

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications_count",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications",
        new_callable=AsyncMock,
    )
    async def test_get_notifications_forwards_filters(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
    ):
        """Query params reach get_user_notifications as the matching filter fields."""
        mock_get.return_value = []
        mock_count.return_value = 0
        response = await client.get(f"{NOTIF_BASE}?status=read&channel_type=email&limit=7&offset=3")
        assert response.status_code == 200

        call = mock_get.await_args
        assert call.args[0] == FAKE_USER_ID
        filters = call.kwargs["filters"]
        assert filters.status == NotificationStatus.READ
        assert filters.channel_type == "email"
        assert filters.limit == 7
        assert filters.offset == 3

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications_count",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications",
        new_callable=AsyncMock,
    )
    async def test_get_notifications_service_error(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
    ):
        mock_get.side_effect = Exception("db error")
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to get notifications"

    async def test_get_notifications_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(NOTIF_BASE)
        assert response.status_code == 401

    async def test_get_notifications_invalid_limit(self, client: AsyncClient):
        response = await client.get(f"{NOTIF_BASE}?limit=999")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /notifications/preferences/channels
# ---------------------------------------------------------------------------


class TestGetChannelPreferences:
    """GET /api/v1/notifications/preferences/channels"""

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_get_channel_preferences_success(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.return_value = {
            "telegram": True,
            "discord": False,
            "whatsapp": False,
            "slack": False,
        }
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 200
        data = response.json()
        assert data["telegram"] is True
        assert data["discord"] is False

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_get_channel_preferences_error(self, mock_fetch: AsyncMock, client: AsyncClient):
        mock_fetch.side_effect = Exception("db fail")
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to get channel preferences"


# ---------------------------------------------------------------------------
# PUT /notifications/preferences/channels
# ---------------------------------------------------------------------------


class TestUpdateChannelPreferences:
    """PUT /api/v1/notifications/preferences/channels"""

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_success(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_fetch.return_value = {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": False,
        }
        with patch("app.api.v1.endpoints.notification.schedule_account_sync") as mock_schedule_sync:
            response = await client.put(
                f"{NOTIF_BASE}/preferences/channels",
                json={"telegram": False, "discord": True},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["telegram"] is False
        assert data["discord"] is True
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_error(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_set_prefs.side_effect = Exception("db fail")
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": True},
        )
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to update channel preferences"


class TestNotificationAnalytics:
    """Analytics captures on notification preference updates."""

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_captures_notifications_toggled(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_fetch.return_value = {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": False,
        }
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.put(
                f"{NOTIF_BASE}/preferences/channels",
                json={"telegram": False, "discord": True},
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.NOTIFICATION_PREFERENCE_UPDATED,
            {
                "changed_channel_count": 2,
                "channels_enabled": ["discord"],
                "channels_disabled": ["telegram"],
            },
        )


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/actions/{action_id}/execute
# ---------------------------------------------------------------------------


class TestExecuteAction:
    """POST /api/v1/notifications/{id}/actions/{aid}/execute"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_success(self, mock_exec: AsyncMock, client: AsyncClient):
        result = MagicMock()
        result.success = True
        result.message = "Done"
        result.data = {"key": "val"}
        mock_exec.return_value = result
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_failure(self, mock_exec: AsyncMock, client: AsyncClient):
        result = MagicMock()
        result.success = False
        result.message = "Action failed"
        mock_exec.return_value = result
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 400

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_exception(self, mock_exec: AsyncMock, client: AsyncClient):
        mock_exec.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to execute action"


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/read
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    """POST /api/v1/notifications/{id}/read"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_success(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.return_value = _make_record()
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["id"] == "n1"
        assert body["data"]["status"] == "read"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_not_found(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.return_value = None
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_error(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to mark notification as read"


# ---------------------------------------------------------------------------
# POST /notifications/bulk-actions
# ---------------------------------------------------------------------------


class TestBulkActions:
    """POST /api/v1/notifications/bulk-actions"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_success(self, mock_bulk: AsyncMock, client: AsyncClient):
        mock_bulk.return_value = {"n1": True, "n2": True}
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1", "n2"], "action": "mark_read"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "2/2" in data["message"]

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_empty_ids(self, mock_bulk: AsyncMock, client: AsyncClient):
        # The empty-ids HTTPException(400) is inside a bare except that
        # re-raises as 500, so the endpoint actually returns 500.
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": [], "action": "mark_read"},
        )
        assert response.status_code == 500

    @patch("app.api.v1.endpoints.notification.log")
    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_error(
        self, mock_bulk: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_bulk.side_effect = Exception("boom")
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1"], "action": "mark_read"},
        )
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to perform bulk actions"
        mock_log.error.assert_called_once_with(
            f"{LogTag.NOTIFICATION} Failed to perform bulk actions",
            user_id=FAKE_USER_ID,
            notification_count=1,
            error_type="Exception",
            error="boom",
        )


# ---------------------------------------------------------------------------
# POST /notifications/mark-all-read
# ---------------------------------------------------------------------------


class TestMarkAllRead:
    """POST /api/v1/notifications/mark-all-read"""

    @patch("app.api.v1.endpoints.notification.log")
    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_all_read",
        new_callable=AsyncMock,
    )
    async def test_mark_all_read_success(
        self, mock_mark_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_mark_all.return_value = 7
        response = await client.post(f"{NOTIF_BASE}/mark-all-read")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["message"] == "Marked 7 notifications as read"
        assert body["data"]["updated_count"] == 7
        mock_mark_all.assert_awaited_once_with(FAKE_USER_ID, channel_type=None)

        first_set, second_set = mock_log.set.call_args_list
        assert first_set.kwargs == {
            "user": {"id": FAKE_USER_ID},
            "operation": "mark_all_read",
            "notification": {"operation": "mark_all_read"},
        }
        assert second_set.kwargs == {"outcome": "success"}
        mock_log.set_ns.assert_called_once_with("notification", result_count=7, success=True)

    @patch("app.api.v1.endpoints.notification.log")
    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_all_read",
        new_callable=AsyncMock,
    )
    async def test_mark_all_read_passes_channel_type(
        self, mock_mark_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_mark_all.return_value = 3
        response = await client.post(f"{NOTIF_BASE}/mark-all-read?channel_type=inapp")

        assert response.status_code == 200
        mock_mark_all.assert_awaited_once_with(FAKE_USER_ID, channel_type="inapp")

        first_set = mock_log.set.call_args_list[0]
        assert first_set.kwargs["notification"] == {
            "operation": "mark_all_read",
            "channel": "inapp",
        }

    @patch("app.api.v1.endpoints.notification.log")
    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_all_read",
        new_callable=AsyncMock,
    )
    async def test_mark_all_read_error(
        self, mock_mark_all: AsyncMock, mock_log: MagicMock, client: AsyncClient
    ):
        mock_mark_all.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/mark-all-read")

        assert response.status_code == 500
        assert response.json()["message"] == "Failed to mark all notifications as read"
        mock_log.error.assert_called_once_with(
            f"{LogTag.NOTIFICATION} Failed to mark all notifications as read",
            user_id=FAKE_USER_ID,
            error_type="Exception",
            error="boom",
        )

    async def test_mark_all_read_no_user_id(self, test_app: FastAPI) -> None:
        """Missing user_id yields 401 with the exact detail string."""
        original = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"user_id": None}
        try:
            transport = ASGITransport(app=test_app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
                response = await ac.post(f"{NOTIF_BASE}/mark-all-read")
        finally:
            if original is None:
                test_app.dependency_overrides.pop(get_current_user, None)
            else:
                test_app.dependency_overrides[get_current_user] = original

        assert response.status_code == 401
        assert response.json()["message"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/register-device
# ---------------------------------------------------------------------------


class TestRegisterDevice:
    """POST /api/v1/notifications/register-device"""

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_success(self, mock_svc_factory: MagicMock, client: AsyncClient):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "ExponentPushToken[abc123]",
                "platform": "ios",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "Device registered successfully"}

    async def test_register_device_invalid_token(self, client: AsyncClient):
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "invalid_token",
                "platform": "ios",
            },
        )
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_limit_exceeded(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 10
        svc.verify_token_ownership.return_value = False
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "ExponentPushToken[abc123]",
                "platform": "ios",
            },
        )
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_service_failure(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.return_value = False
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "ExponentPushToken[abc123]",
                "platform": "ios",
            },
        )
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to register device token"

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_exception(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.side_effect = Exception("boom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "ExponentPushToken[abc123]",
                "platform": "ios",
            },
        )
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to register device token"


# ---------------------------------------------------------------------------
# POST /notifications/unregister-device
# ---------------------------------------------------------------------------


class TestUnregisterDevice:
    """POST /api/v1/notifications/unregister-device"""

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_success(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.unregister_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "Device unregistered successfully"}

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_not_found(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.unregister_device_token.return_value = False
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "Device token not found"}

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_error(self, mock_svc_factory: MagicMock, client: AsyncClient):
        svc = AsyncMock()
        svc.unregister_device_token.side_effect = Exception("boom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to unregister device token"


# ---------------------------------------------------------------------------
# GET /notifications/{notification_id}
# ---------------------------------------------------------------------------


class TestGetNotification:
    """GET /api/v1/notifications/{id}"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_success(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = _make_view()
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == "n1"
        assert data["data"]["content"]["title"] == "Hello"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_not_found(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = None
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_error(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.side_effect = Exception("boom")
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 500
        assert response.json()["message"] == "Failed to get notification"

    async def test_get_notification_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 401
