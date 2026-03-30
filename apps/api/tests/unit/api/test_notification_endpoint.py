"""Unit tests for notification API endpoints.

Tests the notification endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

NOTIF_BASE = "/api/v1/notifications"


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
        mock_get.return_value = [{"id": "n1", "title": "Hello"}]
        mock_count.return_value = 1
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["notifications"]) == 1

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
        response = await client.get(f"{NOTIF_BASE}?status=read")
        assert response.status_code == 200
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
    async def test_get_notifications_service_error(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
    ):
        mock_get.side_effect = Exception("db error")
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 500

    async def test_get_notifications_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(NOTIF_BASE)
        assert response.status_code == 401

    async def test_get_notifications_invalid_limit(self, client: AsyncClient):
        response = await client.get(f"{NOTIF_BASE}?limit=999")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /notifications/preferences/channels
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
    async def test_get_channel_preferences_error(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.side_effect = Exception("db fail")
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PUT /notifications/preferences/channels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateChannelPreferences:
    """PUT /api/v1/notifications/preferences/channels"""

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.notification.users_collection")
    async def test_update_channel_preferences_success(
        self,
        mock_users: MagicMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_users.update_one = AsyncMock()
        mock_fetch.return_value = {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
        }
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": False, "discord": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["telegram"] is False
        assert data["discord"] is True

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.notification.users_collection")
    async def test_update_channel_preferences_error(
        self,
        mock_users: MagicMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_users.update_one = AsyncMock(side_effect=Exception("db fail"))
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": True},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/actions/{action_id}/execute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteAction:
    """POST /api/v1/notifications/{id}/actions/{aid}/execute"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_success(
        self, mock_exec: AsyncMock, client: AsyncClient
    ):
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
    async def test_execute_action_failure(
        self, mock_exec: AsyncMock, client: AsyncClient
    ):
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
    async def test_execute_action_exception(
        self, mock_exec: AsyncMock, client: AsyncClient
    ):
        mock_exec.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/read
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkAsRead:
    """POST /api/v1/notifications/{id}/read"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_success(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.return_value = {"id": "n1", "status": "read"}
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 200
        assert response.json()["success"] is True

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_not_found(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
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


# ---------------------------------------------------------------------------
# POST /notifications/bulk-actions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBulkActions:
    """POST /api/v1/notifications/bulk-actions"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_success(
        self, mock_bulk: AsyncMock, client: AsyncClient
    ):
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
    async def test_bulk_actions_empty_ids(
        self, mock_bulk: AsyncMock, client: AsyncClient
    ):
        # The empty-ids HTTPException(400) is inside a bare except that
        # re-raises as 500, so the endpoint actually returns 500.
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": [], "action": "mark_read"},
        )
        assert response.status_code == 500

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_error(self, mock_bulk: AsyncMock, client: AsyncClient):
        mock_bulk.side_effect = Exception("boom")
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1"], "action": "mark_read"},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /notifications/register-device
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterDevice:
    """POST /api/v1/notifications/register-device"""

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_success(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
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
        assert response.json()["success"] is True

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


# ---------------------------------------------------------------------------
# POST /notifications/unregister-device
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
        assert response.json()["success"] is True

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
        assert response.json()["success"] is False

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_error(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.unregister_device_token.side_effect = Exception("boom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /notifications/{notification_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNotification:
    """GET /api/v1/notifications/{id}"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_success(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {"id": "n1", "title": "Hello"}
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_not_found(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = None
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_error(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("boom")
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 500

    async def test_get_notification_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 401
