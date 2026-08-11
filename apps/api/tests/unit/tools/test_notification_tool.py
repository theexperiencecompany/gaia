"""Unit tests for app.agents.tools.notification_tool.

Hermetic: every external seam (user lookup, notification service, stream
writer, channel preferences, wide-event logger) is mocked, and every
assertion pins the EXACT contract — full result dicts, exact service call
args, exact stream payloads, exact log stamps — so any single-operator
mutation in the module changes an observed value.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.notification.notification_models import (
    BulkActions,
    ChannelConfig,
    ChannelDeliveryStatus,
    NotificationContent,
    NotificationContentView,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.notification_tool"

# ---------------------------------------------------------------------------
# Module-level patch for the wide-event logger: every tool stamps log.set on
# entry and log.error on the failure path. The calls carry the tool's context
# (tool name, action, notification ids), so they are asserted per-test; the
# autouse fixture resets the call history first.
# ---------------------------------------------------------------------------

_log_patch = patch(f"{MODULE}.log", new_callable=MagicMock)
_log_mock = _log_patch.start()

# ---------------------------------------------------------------------------
# Module-level patch for the @with_rate_limiting decorator's seams: every
# tool runs through it, and it stamps result dicts with a `_rate_limit_info`
# key (feature/plan/usage) when the limiter ran. Pinning the seams makes the
# stamp deterministic (and keeps the lane free of real Redis calls);
# _assert_tool_result below asserts the stamp separately from the tool's
# own contract.
# ---------------------------------------------------------------------------

_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

_plan_patch = patch(
    "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
    new_callable=AsyncMock,
    return_value="free",
)
_plan_patch.start()


@pytest.fixture(autouse=True)
def _reset_log_mock() -> None:
    _log_mock.reset_mock()


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _make_notification(
    notification_id: str = "notif-1",
    title: str = "Test Notification",
    body: str = "This is a test",
) -> NotificationView:
    """Create a sample notification view — the shape the service now returns."""
    return NotificationView(
        id=notification_id,
        user_id=FAKE_USER_ID,
        status=NotificationStatus.DELIVERED,
        created_at="2026-01-01T00:00:00+00:00",
        content=NotificationContentView(title=title, body=body),
        source=NotificationSourceEnum.AI_AGENT,
        type=NotificationType.INFO,
    )


def _make_record(
    notification_id: str = "notif-1",
    status: NotificationStatus = NotificationStatus.DELIVERED,
    channels: list[ChannelDeliveryStatus] | None = None,
) -> NotificationRecord:
    """Create a notification record with the given channel outcomes."""
    return NotificationRecord(
        id=notification_id,
        user_id=FAKE_USER_ID,
        status=status,
        created_at=datetime.now(UTC),
        channels=channels or [],
        original_request=NotificationRequest(
            user_id=FAKE_USER_ID,
            source=NotificationSourceEnum.AI_AGENT,
            content=NotificationContent(title="Hello", body="World"),
        ),
    )


def _assert_log_entry(tool_name: str, action: str) -> None:
    """Assert the tool's wide-event context stamp."""
    _log_mock.set.assert_called_once_with(tool={"name": tool_name, "action": action})


def _assert_log_error(message: str) -> None:
    """Assert the tool's failure log line with the raised exception's type name."""
    _log_mock.error.assert_called_once_with(message, error_type="Exception")


def _assert_tool_result(result: dict[str, Any], expected: dict[str, Any]) -> None:
    """Assert the tool's own payload exactly, separating decorator machinery.

    ``@with_rate_limiting`` stamps every dict result with a ``_rate_limit_info``
    key (feature/plan/usage) when rate limiting ran; that is decorator
    metadata, not the tool's contract, so it is asserted separately.
    """
    rate_limit_info = result.pop("_rate_limit_info", None)
    if rate_limit_info is not None:
        assert rate_limit_info == {
            "feature": "notification_operations",
            "plan": "free",
            "usage": {},
        }
    assert result == expected


# ---------------------------------------------------------------------------
# Tests: get_notifications
# ---------------------------------------------------------------------------


class TestGetNotifications:
    """Tests for the get_notifications tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Returns notifications, forwards every filter, and streams the payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)
        config = _make_config()

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=config)

        serialized = [n.model_dump(mode="json") for n in notifications]
        _assert_tool_result(result, {"notifications": serialized})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            status=NotificationStatus.DELIVERED,
            notification_type=None,
            source=None,
            limit=50,
            offset=0,
        )
        writer.assert_called_once_with({"notification_data": {"notifications": serialized}})
        _assert_log_entry("get_notifications", "get")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_serializes_views_in_json_mode(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Views are dumped with mode="json" so enum members never leak into the payload.

        Python-mode dumps keep enum *members* (NotificationStatus is a str-Enum, so
        ``==`` comparisons still pass — the member is a str subclass), which
        LangChain would stringify as ``<NotificationStatus.DELIVERED: 'delivered'>``.
        """
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(return_value=[_make_notification()])

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config())

        payload = result["notifications"][0]
        assert type(payload["status"]) is str
        assert type(payload["source"]) is str
        assert type(payload["type"]) is str

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_forwards_explicit_filters(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Explicit status/type/source/limit/offset args reach the service unchanged."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(return_value=[])
        config = _make_config()

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(
            config=config,
            status=NotificationStatus.READ,
            notification_type=NotificationType.WARNING,
            source=NotificationSourceEnum.AI_AGENT,
            limit=5,
            offset=10,
        )

        _assert_tool_result(result, {"notifications": []})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            status=NotificationStatus.READ,
            notification_type=NotificationType.WARNING,
            source=NotificationSourceEnum.AI_AGENT,
            limit=5,
            offset=10,
        )
        writer.assert_called_once_with({"notification_data": {"notifications": []}})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user_id returns the exact auth error dict and calls nothing."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=config)

        _assert_tool_result(result, {"error": "User authentication required", "notifications": []})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications.assert_not_awaited()
        _assert_log_entry("get_notifications", "get")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns the exact error dict and logs the failure."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(side_effect=Exception("DB error"))

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "DB error", "notifications": []})
        _assert_log_entry("get_notifications", "get")
        _assert_log_error(f"{LogTag.TOOL} Error getting notifications")


# ---------------------------------------------------------------------------
# Tests: search_notifications
# ---------------------------------------------------------------------------


class TestSearchNotifications:
    """Tests for the search_notifications tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path_title_match(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search matches case-insensitively by title and returns the exact payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        matches = [_make_notification(title="Meeting reminder")]
        mock_service.get_user_notifications = AsyncMock(
            return_value=[
                *matches,
                _make_notification(notification_id="notif-2", title="Shopping list"),
            ]
        )
        config = _make_config()

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(config=config, query="meeting")

        serialized = [n.model_dump(mode="json") for n in matches]
        _assert_tool_result(result, {"notifications": serialized})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=None, limit=100, offset=0
        )
        writer.assert_called_once_with({"notification_data": {"notifications": serialized}})
        _assert_log_entry("search_notifications", "search")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_search_body_match(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search matches case-insensitively by body content."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        matches = [_make_notification(body="Your deployment finished")]
        mock_service.get_user_notifications = AsyncMock(return_value=matches)

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="DEPLOYMENT",
        )

        serialized = [n.model_dump(mode="json") for n in matches]
        _assert_tool_result(result, {"notifications": serialized})
        writer.assert_called_once_with({"notification_data": {"notifications": serialized}})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_query_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Whitespace-only query returns the exact error dict and never searches."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock()

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="   ",
        )

        _assert_tool_result(result, {"error": "Search query cannot be empty", "notifications": []})
        mock_service.get_user_notifications.assert_not_awaited()
        _assert_log_entry("search_notifications", "search")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns the exact auth error dict."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(config=config, query="test")

        _assert_tool_result(result, {"error": "User authentication required", "notifications": []})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications.assert_not_awaited()
        _assert_log_entry("search_notifications", "search")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_forwards_status_filter(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """An explicit status filter reaches the search service unchanged."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(return_value=[])

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="meeting",
            status=NotificationStatus.READ,
        )

        _assert_tool_result(result, {"notifications": []})
        mock_service.get_user_notifications.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=NotificationStatus.READ, limit=100, offset=0
        )
        writer.assert_called_once_with({"notification_data": {"notifications": []}})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_serializes_views_in_json_mode(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search results are dumped with mode="json" so enum members never leak."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(return_value=[_make_notification()])

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="Test Notification",
        )

        payload = result["notifications"][0]
        assert type(payload["status"]) is str
        assert type(payload["source"]) is str
        assert type(payload["type"]) is str

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_limit_applied(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search results respect the explicit limit parameter."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        many_notifs = [
            _make_notification(notification_id=f"n-{i}", title="test", body="test body")
            for i in range(10)
        ]
        mock_service.get_user_notifications = AsyncMock(return_value=many_notifs)

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="test",
            limit=3,
        )

        serialized = [n.model_dump(mode="json") for n in many_notifs[:3]]
        _assert_tool_result(result, {"notifications": serialized})
        writer.assert_called_once_with({"notification_data": {"notifications": serialized}})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_default_limit_caps_at_20(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Without an explicit limit, at most 20 matches are returned."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        many_notifs = [
            _make_notification(notification_id=f"n-{i}", title="test", body="test body")
            for i in range(25)
        ]
        mock_service.get_user_notifications = AsyncMock(return_value=many_notifs)

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="test",
        )

        assert len(result["notifications"]) == 20
        writer.assert_called_once_with(
            {"notification_data": {"notifications": result["notifications"]}}
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns the exact error dict and logs the failure."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(side_effect=Exception("DB error"))

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="meeting",
        )

        _assert_tool_result(result, {"error": "DB error", "notifications": []})
        _assert_log_entry("search_notifications", "search")
        _assert_log_error(f"{LogTag.TOOL} Error searching notifications")


# ---------------------------------------------------------------------------
# Tests: get_notification_count
# ---------------------------------------------------------------------------


class TestGetNotificationCount:
    """Tests for the get_notification_count tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Returns the exact count and forwards the status filter."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications_count = AsyncMock(return_value=5)
        config = _make_config()

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=config)

        _assert_tool_result(result, {"count": 5})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications_count.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=None
        )
        _assert_log_entry("get_notification_count", "count")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_forwards_status_filter(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """An explicit status filter reaches the count service unchanged."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications_count = AsyncMock(return_value=3)

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(
            config=_make_config(),
            status=NotificationStatus.PENDING,
        )

        _assert_tool_result(result, {"count": 3})
        mock_service.get_user_notifications_count.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=NotificationStatus.PENDING
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns the exact auth error dict with count 0."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications_count = AsyncMock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=config)

        _assert_tool_result(result, {"error": "User authentication required", "count": 0})
        mock_get_user.assert_called_once_with(config)
        mock_service.get_user_notifications_count.assert_not_awaited()
        _assert_log_entry("get_notification_count", "count")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service error returns the exact error dict with count 0."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications_count = AsyncMock(
            side_effect=Exception("connection lost")
        )

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "connection lost", "count": 0})
        _assert_log_entry("get_notification_count", "count")
        _assert_log_error(f"{LogTag.TOOL} Error getting notification count")


# ---------------------------------------------------------------------------
# Tests: mark_notifications_read
# ---------------------------------------------------------------------------


class TestMarkNotificationsRead:
    """Tests for the mark_notifications_read tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_single_notification(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """One id goes to mark_as_read, never to the bulk path."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.mark_as_read = AsyncMock(return_value=True)
        mock_service.bulk_actions = AsyncMock()
        config = _make_config()

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=config,
            notification_ids=["notif-1"],
        )

        _assert_tool_result(result, {"success": True})
        mock_get_user.assert_called_once_with(config)
        mock_service.mark_as_read.assert_awaited_once_with("notif-1", FAKE_USER_ID)
        mock_service.bulk_actions.assert_not_awaited()
        _assert_log_entry("mark_notifications_read", "mark_read")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_single_notification_failed(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """A falsy mark_as_read result yields success False."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.mark_as_read = AsyncMock(return_value=None)

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        _assert_tool_result(result, {"success": False})
        mock_service.mark_as_read.assert_awaited_once_with("notif-1", FAKE_USER_ID)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_bulk_notifications(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Multiple ids go to bulk_actions with MARK_READ, never to mark_as_read."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.bulk_actions = AsyncMock(return_value={"notif-1": True, "notif-2": True})
        mock_service.mark_as_read = AsyncMock()
        config = _make_config()

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=config,
            notification_ids=["notif-1", "notif-2"],
        )

        _assert_tool_result(result, {"success": True})
        mock_get_user.assert_called_once_with(config)
        mock_service.bulk_actions.assert_awaited_once_with(
            notification_ids=["notif-1", "notif-2"],
            user_id=FAKE_USER_ID,
            action=BulkActions.MARK_READ,
        )
        mock_service.mark_as_read.assert_not_awaited()
        _assert_log_entry("mark_notifications_read", "mark_read")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_bulk_success_when_any_succeeded(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Bulk success is True when at least one id was updated."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.bulk_actions = AsyncMock(return_value={"notif-1": True, "notif-2": False})

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1", "notif-2"],
        )

        _assert_tool_result(result, {"success": True})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_bulk_failure_when_none_succeeded(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Bulk success is False when every id failed to update."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.bulk_actions = AsyncMock(return_value={"notif-1": False, "notif-2": False})

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1", "notif-2"],
        )

        _assert_tool_result(result, {"success": False})

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_ids_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty notification IDs list returns the exact error dict, no service call."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.mark_as_read = AsyncMock()
        mock_service.bulk_actions = AsyncMock()

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=[],
        )

        _assert_tool_result(result, {"error": "No notification IDs provided", "success": False})
        mock_service.mark_as_read.assert_not_awaited()
        mock_service.bulk_actions.assert_not_awaited()
        _assert_log_entry("mark_notifications_read", "mark_read")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns the exact auth error dict."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.mark_as_read = AsyncMock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=config,
            notification_ids=["notif-1"],
        )

        _assert_tool_result(result, {"error": "User authentication required", "success": False})
        mock_get_user.assert_called_once_with(config)
        mock_service.mark_as_read.assert_not_awaited()
        _assert_log_entry("mark_notifications_read", "mark_read")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns the exact error dict and logs the failure."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.mark_as_read = AsyncMock(side_effect=Exception("service down"))

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        _assert_tool_result(result, {"error": "service down", "success": False})
        _assert_log_entry("mark_notifications_read", "mark_read")
        _assert_log_error(f"{LogTag.TOOL} Error marking notifications as read")


# ---------------------------------------------------------------------------
# Tests: send_notification
# ---------------------------------------------------------------------------


class TestSendNotification:
    """Tests for the send_notification tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Sends on the named channels, trims copy, and returns the exact result."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        record = _make_record(
            channels=[
                ChannelDeliveryStatus(
                    channel_type="whatsapp", status=NotificationStatus.DELIVERED, skipped=False
                ),
                ChannelDeliveryStatus(
                    channel_type="telegram", status=NotificationStatus.DELIVERED, skipped=True
                ),
                ChannelDeliveryStatus(
                    channel_type="discord", status=NotificationStatus.FAILED, skipped=False
                ),
            ]
        )
        mock_service.create_notification = AsyncMock(return_value=record)
        config = _make_config()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=config,
            message="  Hello  ",
            title="  Hi  ",
            channels=["whatsapp", "telegram"],
            notification_type=NotificationType.WARNING,
        )

        expected = {
            "success": True,
            "notification_id": "notif-1",
            "title": "Hi",
            "message": "Hello",
            "notification_type": "warning",
            "status": "delivered",
            "delivered_channels": ["whatsapp"],
        }
        _assert_tool_result(result, expected)
        mock_get_user.assert_called_once_with(config)
        mock_service.create_notification.assert_awaited_once()
        sent_request = mock_service.create_notification.await_args.args[0]
        assert isinstance(sent_request, NotificationRequest)
        assert sent_request.user_id == FAKE_USER_ID
        assert sent_request.source == NotificationSourceEnum.AI_AGENT
        assert sent_request.type == NotificationType.WARNING
        assert sent_request.channels == [
            ChannelConfig(channel_type="whatsapp"),
            ChannelConfig(channel_type="telegram"),
        ]
        assert sent_request.content == NotificationContent(title="Hi", body="Hello")
        writer.assert_called_once_with({"send_notification_data": result})
        assert _log_mock.set.call_args_list == [
            call(tool={"name": "send_notification", "action": "send"}),
            call(
                tool={
                    "name": "send_notification",
                    "notification_id": "notif-1",
                    "status": "delivered",
                    "delivered_channels": ["whatsapp"],
                }
            ),
        ]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_default_type_when_none_passed(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """An explicit None notification_type resolves to INFO."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        record = _make_record(
            channels=[
                ChannelDeliveryStatus(
                    channel_type="whatsapp", status=NotificationStatus.DELIVERED, skipped=False
                ),
            ]
        )
        mock_service.create_notification = AsyncMock(return_value=record)

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="Hi",
            channels=["whatsapp"],
            notification_type=None,
        )

        assert result["success"] is True
        assert result["notification_type"] == "info"
        sent_request = mock_service.create_notification.await_args.args[0]
        assert sent_request.type == NotificationType.INFO

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_message_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Whitespace-only message returns the exact error dict, no send."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="   ",
            title="Hi",
            channels=["whatsapp"],
        )

        _assert_tool_result(
            result, {"error": "Notification message cannot be empty", "success": False}
        )
        mock_service.create_notification.assert_not_awaited()
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_title_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Whitespace-only title returns the exact error dict, no send."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="  ",
            channels=["whatsapp"],
        )

        _assert_tool_result(
            result, {"error": "Notification title cannot be empty", "success": False}
        )
        mock_service.create_notification.assert_not_awaited()
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_channels_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty channels returns the exact 'channels is required' error, no send."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="Hi",
            channels=[],
        )

        _assert_tool_result(
            result,
            {
                "error": (
                    "channels is required — specify which channel(s) to notify "
                    "(inapp, telegram, discord, whatsapp, slack). If the user did not name a "
                    "channel, ask them which one(s) they want before sending."
                ),
                "success": False,
            },
        )
        mock_service.create_notification.assert_not_awaited()
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_unknown_channels_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Unknown channel names return the exact error with valid alternatives."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="Hi",
            channels=["bogus", "nope"],
        )

        _assert_tool_result(
            result,
            {
                "error": (
                    "Unknown channel(s): bogus, nope. "
                    "Valid channels: inapp, telegram, discord, whatsapp, slack."
                ),
                "success": False,
            },
        )
        mock_service.create_notification.assert_not_awaited()
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_create_failure_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """A None record from the service returns the exact failure error."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(return_value=None)

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="Hi",
            channels=["whatsapp"],
        )

        _assert_tool_result(result, {"error": "Failed to create notification", "success": False})
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns the exact auth error dict."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=config,
            message="Hello",
            title="Hi",
            channels=["whatsapp"],
        )

        _assert_tool_result(result, {"error": "User authentication required", "success": False})
        mock_get_user.assert_called_once_with(config)
        mock_service.create_notification.assert_not_awaited()
        _assert_log_entry("send_notification", "send")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns the exact error dict and logs the failure."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=Exception("boom"))

        from app.agents.tools.notification_tool import send_notification

        result = await send_notification.coroutine(
            config=_make_config(),
            message="Hello",
            title="Hi",
            channels=["whatsapp"],
        )

        _assert_tool_result(result, {"error": "boom", "success": False})
        _assert_log_entry("send_notification", "send")
        _assert_log_error(f"{LogTag.TOOL} Error sending notification")


# ---------------------------------------------------------------------------
# Tests: get_notification_preferences
# ---------------------------------------------------------------------------


class TestGetNotificationPreferences:
    """Tests for the get_notification_preferences tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_channel_preferences", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Returns normalized preferences with inapp always enabled last."""
        mock_writer_factory.return_value = _writer_mock()
        mock_fetch.return_value = {"whatsapp": True, "telegram": False}
        config = _make_config()

        from app.agents.tools.notification_tool import get_notification_preferences

        result = await get_notification_preferences.coroutine(config=config)

        _assert_tool_result(
            result,
            {
                "preferences": {"whatsapp": True, "telegram": False, "inapp": True},
                "available_channels": ["whatsapp", "telegram", "inapp"],
                "enabled_channels": ["whatsapp", "inapp"],
            },
        )
        mock_get_user.assert_called_once_with(config)
        mock_fetch.assert_awaited_once_with(FAKE_USER_ID)
        _assert_log_entry("get_notification_preferences", "get")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_channel_preferences", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns the exact auth error dict."""
        mock_writer_factory.return_value = _writer_mock()
        config = _make_config_no_user()

        from app.agents.tools.notification_tool import get_notification_preferences

        result = await get_notification_preferences.coroutine(config=config)

        _assert_tool_result(result, {"error": "User authentication required", "preferences": {}})
        mock_get_user.assert_called_once_with(config)
        mock_fetch.assert_not_awaited()
        _assert_log_entry("get_notification_preferences", "get")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_channel_preferences", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns the exact error dict and logs the failure."""
        mock_writer_factory.return_value = _writer_mock()
        mock_fetch.side_effect = Exception("boom")

        from app.agents.tools.notification_tool import get_notification_preferences

        result = await get_notification_preferences.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "boom", "preferences": {}})
        _assert_log_entry("get_notification_preferences", "get")
        _assert_log_error(f"{LogTag.TOOL} Error fetching notification preferences")
