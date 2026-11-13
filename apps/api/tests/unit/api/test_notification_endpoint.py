"""Unit tests for the channel preference, device and unsubscribe endpoints.

Tests the notification endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsNotificationsToggled

NOTIF_BASE = "/api/v1/notifications"
ANALYTICS_PATCH = "app.api.v1.endpoints.notification.capture"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


FAKE_USER_ID = "507f1f77bcf86cd799439011"


# ---------------------------------------------------------------------------
# GET /notifications/preferences/channels
# ---------------------------------------------------------------------------


class TestGetChannelPreferences:
    """GET /api/v1/notifications/preferences/channels."""

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
    """PUT /api/v1/notifications/preferences/channels."""

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
            UserId(FAKE_USER_ID),
            SettingsNotificationsToggled(
                changed_channel_count=2,
                channels_enabled=["discord"],
                channels_disabled=["telegram"],
            ),
        )


# ---------------------------------------------------------------------------
# POST /notifications/register-device
# ---------------------------------------------------------------------------


class TestRegisterDevice:
    """POST /api/v1/notifications/register-device."""

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
    """POST /api/v1/notifications/unregister-device."""

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
