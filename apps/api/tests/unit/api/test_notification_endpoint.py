"""Unit tests for notification API endpoints.

Tests the notification endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation. Mocked
services are asserted on exact arguments; the wide-event accumulator
is asserted so log fields are part of the contract.
"""

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from html import escape
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints.notification import _UNSUBSCRIBE_INVALID_HTML
from app.constants.log_tags import LogTag
from app.constants.notifications import MAX_DEVICES_PER_USER
from app.models.device_token_models import PlatformType
from app.models.notification.notification_models import (
    BulkActions,
    NotificationContent,
    NotificationContentView,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from shared.py.wide_events import log

NOTIF_BASE = "/api/v1/notifications"

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def wide_event() -> Callable[[], dict[str, Any]]:
    """Bind a fresh wide-event accumulator and return a reader for it."""
    log.reset()
    return log.get


def _user_without_id() -> dict[str, Any]:
    return {}


@pytest.fixture
async def client_without_user_id(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated client whose current user has no ``user_id`` (the 401 branch)."""
    original = test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_current_user] = _user_without_id
    try:
        transport = ASGITransport(app=test_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",  # NOSONAR
        ) as ac:
            yield ac
    finally:
        test_app.dependency_overrides.pop(get_current_user, None)
        if original is not None:
            test_app.dependency_overrides[get_current_user] = original


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


def _notif_tag(message: str) -> str:
    return f"{LogTag.NOTIFICATION} {message}"


# ---------------------------------------------------------------------------
# GET /notifications/unsubscribe
# ---------------------------------------------------------------------------


class TestUnsubscribeConfirmation:
    """GET /api/v1/notifications/unsubscribe — no login required."""

    @patch("app.api.v1.endpoints.notification.verify_unsubscribe_token")
    async def test_invalid_token_returns_400_page(
        self, mock_verify: MagicMock, client: AsyncClient
    ):
        mock_verify.return_value = None
        response = await client.get(f"{NOTIF_BASE}/unsubscribe?token=bad")
        assert response.status_code == 400
        assert response.text == _UNSUBSCRIBE_INVALID_HTML

    @patch("app.api.v1.endpoints.notification.verify_unsubscribe_token")
    async def test_valid_token_renders_confirmation_form(
        self,
        mock_verify: MagicMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        token = '<script>"quote"'
        mock_verify.return_value = FAKE_USER_ID
        response = await client.get(f"{NOTIF_BASE}/unsubscribe?token={token}")
        assert response.status_code == 200
        mock_verify.assert_called_once_with(token)
        assert "Want to stop receiving GAIA emails?" in response.text
        assert "Unsubscribe" in response.text
        assert (
            f"action='/api/v1/notifications/unsubscribe?token={escape(token)}'"
            in response.text
        )
        assert escape(token) in response.text
        assert "<script>" not in response.text
        assert "XX" not in response.text
        assert (
            "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
            in response.text
        )
        assert (
            "<button style='background-color: #00bbff; color: #ffffff; padding: 8px 16px; "
            in response.text
        )
        assert "</form></body></html>" in response.text
        assert wide_event()["operation"] == "unsubscribe_email_confirmation"


# ---------------------------------------------------------------------------
# POST /notifications/unsubscribe
# ---------------------------------------------------------------------------


class TestUnsubscribeFromEmails:
    """POST /api/v1/notifications/unsubscribe — RFC 8058 one-click target."""

    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.notification.verify_unsubscribe_token")
    async def test_invalid_token_returns_blank_400(
        self,
        mock_verify: MagicMock,
        mock_set_prefs: AsyncMock,
        client: AsyncClient,
    ):
        mock_verify.return_value = None
        response = await client.post(f"{NOTIF_BASE}/unsubscribe?token=bad")
        assert response.status_code == 400
        assert response.text == ""
        mock_set_prefs.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.notification.verify_unsubscribe_token")
    async def test_valid_token_disables_email(
        self,
        mock_verify: MagicMock,
        mock_set_prefs: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_verify.return_value = FAKE_USER_ID
        response = await client.post(f"{NOTIF_BASE}/unsubscribe?token=good")
        assert response.status_code == 200
        assert response.text == ""
        mock_verify.assert_called_once_with("good")
        mock_set_prefs.assert_awaited_once_with(FAKE_USER_ID, email=False)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "unsubscribe_email_one_click"
        assert fields["outcome"] == "success"


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------


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
        wide_event: Callable[[], dict[str, Any]],
    ):
        views = [_make_view("n1"), _make_view("n2", title="Second")]
        mock_get.return_value = views
        mock_count.return_value = 7
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 200
        assert response.json() == {
            "notifications": [view.model_dump(mode="json") for view in views],
            "total": 7,
            "limit": 50,
            "offset": 0,
        }
        mock_get.assert_awaited_once_with(FAKE_USER_ID, None, 51, 0, None)
        mock_count.assert_awaited_once_with(FAKE_USER_ID, None, None)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "list"
        assert fields["notification"] == {
            "operation": "list",
            "result_count": 2,
            "success": True,
        }
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications_count",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_user_notifications",
        new_callable=AsyncMock,
    )
    async def test_get_notifications_with_filters(
        self,
        mock_get: AsyncMock,
        mock_count: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_get.return_value = []
        mock_count.return_value = 0
        response = await client.get(
            f"{NOTIF_BASE}?status=read&limit=25&offset=10&channel_type=email"
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {"notifications": [], "total": 0, "limit": 25, "offset": 10}
        mock_get.assert_awaited_once_with(
            FAKE_USER_ID, NotificationStatus.READ, 26, 10, "email"
        )
        mock_count.assert_awaited_once_with(FAKE_USER_ID, NotificationStatus.READ, "email")
        assert wide_event()["notification"] == {
            "operation": "list",
            "channel": "email",
            "result_count": 0,
            "success": True,
        }

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
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_get.side_effect = Exception("db error")
        response = await client.get(NOTIF_BASE)
        assert response.status_code == 500
        assert response.json()["detail"] == "db error"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to get notifications"),
            "user_id": FAKE_USER_ID,
            "error_type": "Exception",
            "error": "db error",
        }

    async def test_get_notifications_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(NOTIF_BASE)
        assert response.status_code == 401

    async def test_get_notifications_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.get(NOTIF_BASE)
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"

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
        self,
        mock_fetch: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_fetch.return_value = {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": True,
        }
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 200
        assert response.json() == {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": True,
        }
        mock_fetch.assert_awaited_once_with(FAKE_USER_ID)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "get_channel_preferences"
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_get_channel_preferences_complementary_values(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.return_value = {
            "telegram": True,
            "discord": False,
            "whatsapp": True,
            "slack": False,
        }
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 200
        assert response.json() == {
            "telegram": True,
            "discord": False,
            "whatsapp": True,
            "slack": False,
        }

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_get_channel_preferences_error(
        self,
        mock_fetch: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_fetch.side_effect = Exception("db fail")
        response = await client.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 500
        assert response.json()["detail"] == "db fail"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to get channel preferences"),
            "user_id": FAKE_USER_ID,
            "error_type": "Exception",
            "error": "db fail",
        }

    async def test_get_channel_preferences_missing_user_id(
        self, client_without_user_id: AsyncClient
    ):
        response = await client_without_user_id.get(f"{NOTIF_BASE}/preferences/channels")
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


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
    async def test_update_channel_preferences_partial(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_fetch.return_value = {
            "telegram": True,
            "discord": False,
            "whatsapp": True,
            "slack": False,
        }
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": False, "discord": True},
        )
        assert response.status_code == 200
        assert response.json() == {
            "telegram": True,
            "discord": False,
            "whatsapp": True,
            "slack": False,
        }
        mock_set_prefs.assert_awaited_once_with(
            FAKE_USER_ID,
            telegram=False,
            discord=True,
            whatsapp=None,
            slack=None,
        )
        mock_fetch.assert_awaited_once_with(FAKE_USER_ID)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["notification"] == {
            "channel_preferences_update": {"telegram": False, "discord": True}
        }
        assert fields["operation"] == "update_channel_preferences"
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_full(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_fetch.return_value = {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": True,
        }
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={
                "telegram": True,
                "discord": True,
                "whatsapp": True,
                "slack": True,
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "telegram": False,
            "discord": True,
            "whatsapp": False,
            "slack": True,
        }
        mock_set_prefs.assert_awaited_once_with(
            FAKE_USER_ID,
            telegram=True,
            discord=True,
            whatsapp=True,
            slack=True,
        )

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_set_error(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_set_prefs.side_effect = Exception("db fail")
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": True},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "db fail"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to update channel preferences"),
            "user_id": FAKE_USER_ID,
            "error_type": "Exception",
            "error": "db fail",
        }

    @patch(
        "app.api.v1.endpoints.notification.fetch_channel_preferences",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.notification.user_repository.set_channel_preferences",
        new_callable=AsyncMock,
    )
    async def test_update_channel_preferences_fetch_error(
        self,
        mock_set_prefs: AsyncMock,
        mock_fetch: AsyncMock,
        client: AsyncClient,
    ):
        mock_set_prefs.return_value = None
        mock_fetch.side_effect = Exception("fetch fail")
        response = await client.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": True},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "fetch fail"

    async def test_update_channel_preferences_missing_user_id(
        self, client_without_user_id: AsyncClient
    ):
        response = await client_without_user_id.put(
            f"{NOTIF_BASE}/preferences/channels",
            json={"telegram": True},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/actions/{action_id}/execute
# ---------------------------------------------------------------------------


class TestExecuteAction:
    """POST /api/v1/notifications/{id}/actions/{aid}/execute"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_success(
        self,
        mock_exec: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        result = MagicMock()
        result.success = True
        result.message = "Done"
        result.data = {"key": "val"}
        mock_exec.return_value = result
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Done",
            "data": {"key": "val"},
        }
        mock_exec.assert_awaited_once_with("n1", "a1", FAKE_USER_ID, request=ANY)
        assert mock_exec.await_args is not None
        assert mock_exec.await_args.kwargs["request"] is not None
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "execute_action"
        assert fields["notification"] == {
            "operation": "dispatch",
            "notification_id": "n1",
            "success": True,
        }
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_success_without_message(
        self, mock_exec: AsyncMock, client: AsyncClient
    ):
        result = MagicMock()
        result.success = True
        result.message = None
        result.data = None
        mock_exec.return_value = result
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Action executed successfully",
            "data": None,
        }

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
        assert response.json()["detail"] == "Action failed"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_exception(
        self,
        mock_exec: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_exec.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to execute action"),
            "user_id": FAKE_USER_ID,
            "notification_id": "n1",
            "error_type": "Exception",
            "error": "boom",
        }

    @patch(
        "app.api.v1.endpoints.notification.notification_service.execute_action",
        new_callable=AsyncMock,
    )
    async def test_execute_action_http_exception_passthrough(
        self, mock_exec: AsyncMock, client: AsyncClient
    ):
        mock_exec.side_effect = HTTPException(status_code=418, detail="custom")
        response = await client.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 418
        assert response.json()["detail"] == "custom"

    async def test_execute_action_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.post(f"{NOTIF_BASE}/n1/actions/a1/execute")
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/{notification_id}/read
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    """POST /api/v1/notifications/{id}/read"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_success(
        self,
        mock_mark: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        record = _make_record()
        mock_mark.return_value = record
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Notification marked as read",
            "data": record.model_dump(mode="json"),
        }
        mock_mark.assert_awaited_once_with("n1", FAKE_USER_ID)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "mark_read"
        assert fields["notification"] == {
            "operation": "read",
            "notification_id": "n1",
            "success": True,
        }
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_not_found(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.return_value = None
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 404
        assert response.json()["detail"] == "Notification not found"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_error(
        self,
        mock_mark: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_mark.side_effect = Exception("boom")
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to mark notification as read"),
            "user_id": FAKE_USER_ID,
            "notification_id": "n1",
            "error_type": "Exception",
            "error": "boom",
        }

    @patch(
        "app.api.v1.endpoints.notification.notification_service.mark_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_http_exception_passthrough(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.side_effect = HTTPException(status_code=418, detail="custom")
        response = await client.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 418
        assert response.json()["detail"] == "custom"

    async def test_mark_as_read_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.post(f"{NOTIF_BASE}/n1/read")
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/bulk-actions
# ---------------------------------------------------------------------------


class TestBulkActions:
    """POST /api/v1/notifications/bulk-actions"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_success(
        self,
        mock_bulk: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_bulk.return_value = {"n1": True, "n2": False, "n3": True}
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1", "n2", "n3"], "action": "mark_read"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Bulk action completed: 2/3 successful",
            "data": {
                "results": {"n1": True, "n2": False, "n3": True},
                "successful": 2,
                "total": 3,
            },
        }
        mock_bulk.assert_awaited_once_with(["n1", "n2", "n3"], FAKE_USER_ID, BulkActions.MARK_READ)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["notification"] == {
            "operation": "mark_all_read",
            "result_count": 2,
            "success": False,
        }
        assert fields["operation"] == "bulk_actions"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_tally_from_results_not_ids(
        self, mock_bulk: AsyncMock, client: AsyncClient
    ):
        mock_bulk.return_value = {"x1": True, "x2": False}
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1", "n2", "n3"], "action": "mark_read"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Bulk action completed: 1/2 successful"
        assert response.json()["data"] == {
            "results": {"x1": True, "x2": False},
            "successful": 1,
            "total": 2,
        }

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_all_success_log_flag(
        self,
        mock_bulk: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_bulk.return_value = {"n1": True, "n2": True}
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1", "n2"], "action": "mark_read"},
        )
        assert response.status_code == 200
        assert wide_event()["notification"] == {
            "operation": "mark_all_read",
            "result_count": 2,
            "success": True,
        }

    @patch("app.api.v1.endpoints.notification.log.set", wraps=log.set)
    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_log_context(
        self, mock_bulk: AsyncMock, mock_set: MagicMock, client: AsyncClient
    ):
        mock_bulk.return_value = {"n1": True, "n2": True}
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1", "n2"], "action": "mark_read"},
        )
        assert response.status_code == 200
        mock_set.assert_any_call(
            user={"id": FAKE_USER_ID},
            operation="bulk_actions",
            notification={"operation": "mark_all_read", "result_count": 2},
        )

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_empty_ids(
        self,
        mock_bulk: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        # The empty-ids HTTPException(400) is inside a bare except that
        # re-raises as 500, so the endpoint actually returns 500.
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": [], "action": "mark_read"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "400: No notification IDs provided"
        mock_bulk.assert_not_awaited()
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to perform bulk actions"),
            "user_id": FAKE_USER_ID,
            "notification_count": 0,
            "error_type": "HTTPException",
            "error": "400: No notification IDs provided",
        }

    @patch(
        "app.api.v1.endpoints.notification.notification_service.bulk_actions",
        new_callable=AsyncMock,
    )
    async def test_bulk_actions_error(
        self,
        mock_bulk: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_bulk.side_effect = Exception("boom")
        response = await client.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1"], "action": "mark_read"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to perform bulk actions"),
            "user_id": FAKE_USER_ID,
            "notification_count": 1,
            "error_type": "Exception",
            "error": "boom",
        }

    async def test_bulk_actions_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.post(
            f"{NOTIF_BASE}/bulk-actions",
            json={"notification_ids": ["n1"], "action": "mark_read"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/register-device
# ---------------------------------------------------------------------------


class TestRegisterDevice:
    """POST /api/v1/notifications/register-device"""

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_success(
        self,
        mock_svc_factory: MagicMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={
                "token": "ExponentPushToken[abc123]",
                "platform": "android",
                "device_id": "dev-1",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "Device registered successfully"}
        svc.get_user_device_count.assert_awaited_once_with(FAKE_USER_ID)
        svc.register_device_token.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            token="ExponentPushToken[abc123]",
            platform=PlatformType.ANDROID,
            device_id="dev-1",
        )
        svc.verify_token_ownership.assert_not_awaited()
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["device"] == {
            "platform": PlatformType.ANDROID,
            "device_id": "dev-1",
        }
        assert fields["operation"] == "register_device"
        assert fields["outcome"] == "success"

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_ios_without_device_id(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExpoPushToken[xyz_9]",
                  "platform": "ios"},
        )
        assert response.status_code == 200
        svc.register_device_token.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            token="ExpoPushToken[xyz_9]",
            platform=PlatformType.IOS,
            device_id=None,
        )

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_invalid_token(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "invalid_token", "platform": "ios"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Invalid push token format. Expected ExponentPushToken[...]"
        )
        svc.register_device_token.assert_not_awaited()

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_at_device_limit_not_owned(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = MAX_DEVICES_PER_USER
        svc.verify_token_ownership.return_value = False
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            f"Maximum {MAX_DEVICES_PER_USER} devices allowed per user"
        )
        svc.register_device_token.assert_not_awaited()

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_at_device_limit_owned(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = MAX_DEVICES_PER_USER
        svc.verify_token_ownership.return_value = True
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 200
        svc.verify_token_ownership.assert_awaited_once_with(
            "ExponentPushToken[abc123]", FAKE_USER_ID
        )
        svc.register_device_token.assert_awaited_once()

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_over_device_limit(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = MAX_DEVICES_PER_USER + 1
        svc.verify_token_ownership.return_value = False
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            f"Maximum {MAX_DEVICES_PER_USER} devices allowed per user"
        )

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_below_limit_skips_ownership_check(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = MAX_DEVICES_PER_USER - 1
        svc.register_device_token.return_value = True
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 200
        svc.verify_token_ownership.assert_not_awaited()

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
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to register device token"

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_exception(
        self,
        mock_svc_factory: MagicMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.side_effect = Exception("boom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to register device token"),
            "user_id": FAKE_USER_ID,
            "error_type": "Exception",
            "error": "boom",
        }

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_register_device_http_exception_passthrough(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.get_user_device_count.return_value = 0
        svc.register_device_token.side_effect = HTTPException(status_code=418, detail="custom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 418
        assert response.json()["detail"] == "custom"

    async def test_register_device_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.post(
            f"{NOTIF_BASE}/register-device",
            json={"token": "ExponentPushToken[abc123]", "platform": "ios"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# POST /notifications/unregister-device
# ---------------------------------------------------------------------------


class TestUnregisterDevice:
    """POST /api/v1/notifications/unregister-device"""

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_success(
        self,
        mock_svc_factory: MagicMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
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
        svc.unregister_device_token.assert_awaited_once_with(
            "ExponentPushToken[abc123]", FAKE_USER_ID
        )
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "unregister_device"
        assert fields["outcome"] == "success"

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
    async def test_unregister_device_error(
        self,
        mock_svc_factory: MagicMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        svc = AsyncMock()
        svc.unregister_device_token.side_effect = Exception("boom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to unregister device token"),
            "user_id": FAKE_USER_ID,
            "error_type": "Exception",
            "error": "boom",
        }

    @patch("app.api.v1.endpoints.notification.get_device_token_service")
    async def test_unregister_device_http_exception_passthrough(
        self, mock_svc_factory: MagicMock, client: AsyncClient
    ):
        svc = AsyncMock()
        svc.unregister_device_token.side_effect = HTTPException(status_code=418, detail="custom")
        mock_svc_factory.return_value = svc
        response = await client.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 418
        assert response.json()["detail"] == "custom"

    async def test_unregister_device_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.post(
            f"{NOTIF_BASE}/unregister-device",
            json={"token": "ExponentPushToken[abc123]"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"


# ---------------------------------------------------------------------------
# GET /notifications/{notification_id}
# ---------------------------------------------------------------------------


class TestGetNotification:
    """GET /api/v1/notifications/{id}"""

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_success(
        self,
        mock_get: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        view = _make_view()
        mock_get.return_value = view
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Notification retrieved successfully",
            "data": view.model_dump(mode="json"),
        }
        mock_get.assert_awaited_once_with("n1", FAKE_USER_ID)
        fields = wide_event()
        assert fields["user"] == {"id": FAKE_USER_ID}
        assert fields["operation"] == "get"
        assert fields["notification"] == {
            "operation": "read",
            "notification_id": "n1",
            "success": True,
        }
        assert fields["outcome"] == "success"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_not_found(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = None
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 404
        assert response.json()["detail"] == "Notification not found"

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_error(
        self,
        mock_get: AsyncMock,
        client: AsyncClient,
        wide_event: Callable[[], dict[str, Any]],
    ):
        mock_get.side_effect = Exception("boom")
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 500
        assert response.json()["detail"] == "boom"
        assert wide_event()["errors"][0] == {
            "msg": _notif_tag("Failed to get notification"),
            "user_id": FAKE_USER_ID,
            "notification_id": "n1",
            "error_type": "Exception",
            "error": "boom",
        }

    @patch(
        "app.api.v1.endpoints.notification.notification_service.get_notification",
        new_callable=AsyncMock,
    )
    async def test_get_notification_http_exception_passthrough(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = HTTPException(status_code=418, detail="custom")
        response = await client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 418
        assert response.json()["detail"] == "custom"

    async def test_get_notification_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 401

    async def test_get_notification_missing_user_id(self, client_without_user_id: AsyncClient):
        response = await client_without_user_id.get(f"{NOTIF_BASE}/n1")
        assert response.status_code == 401
        assert response.json()["detail"] == "User not authenticated or user_id not found"
