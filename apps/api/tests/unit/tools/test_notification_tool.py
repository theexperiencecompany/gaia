"""Unit tests for app.agents.tools.notification_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.notification_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> Dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _make_notification(
    notification_id: str = "notif-1",
    title: str = "Test Notification",
    body: str = "This is a test",
) -> Dict[str, Any]:
    """Create a sample notification dict."""
    return {
        "id": notification_id,
        "content": {"title": title, "body": body},
        "status": "delivered",
        "type": "info",
    }


# ---------------------------------------------------------------------------
# Tests: get_notifications
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
        """Returns notifications successfully."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config())

        assert result["notifications"] == notifications
        assert "error" not in result
        mock_service.get_user_notifications.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user_id returns auth error."""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["notifications"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns error response."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(
            side_effect=Exception("DB error")
        )

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config())

        assert "DB error" in result["error"]
        assert result["notifications"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_streams_notification_data(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Notification data is streamed to frontend."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)

        from app.agents.tools.notification_tool import get_notifications

        await get_notifications.coroutine(config=_make_config())

        notif_calls = [
            c for c in writer.call_args_list if "notification_data" in c[0][0]
        ]
        assert len(notif_calls) == 1
        assert (
            notif_calls[0][0][0]["notification_data"]["notifications"] == notifications
        )


# ---------------------------------------------------------------------------
# Tests: search_notifications
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
        """Search matches by title."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(
            return_value=[
                _make_notification(title="Meeting reminder"),
                _make_notification(notification_id="notif-2", title="Shopping list"),
            ]
        )

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="meeting",
        )

        assert len(result["notifications"]) == 1
        assert result["notifications"][0]["content"]["title"] == "Meeting reminder"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_search_body_match(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search matches by body content."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.get_user_notifications = AsyncMock(
            return_value=[
                _make_notification(body="Your deployment finished"),
            ]
        )

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="deployment",
        )

        assert len(result["notifications"]) == 1

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_query_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty search query returns error."""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="   ",
        )

        assert "error" in result
        assert "cannot be empty" in result["error"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing user returns auth error."""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.notification_tool import search_notifications

        result = await search_notifications.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert result["error"] == "User authentication required"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_limit_applied(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Search results respect the limit parameter."""
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

        assert len(result["notifications"]) == 3


# ---------------------------------------------------------------------------
# Tests: get_notification_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNotificationCount:
    """Tests for the get_notification_count tool."""

    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        """Returns count of notifications."""
        mock_service.get_user_notifications_count = AsyncMock(return_value=5)

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=_make_config())

        assert result["count"] == 5

    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
    ) -> None:
        """Missing user returns auth error with count 0."""
        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["count"] == 0

    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        """Service error returns count 0."""
        mock_service.get_user_notifications_count = AsyncMock(
            side_effect=Exception("connection lost")
        )

        from app.agents.tools.notification_tool import get_notification_count

        result = await get_notification_count.coroutine(config=_make_config())

        assert result["count"] == 0
        assert "connection lost" in result["error"]


# ---------------------------------------------------------------------------
# Tests: mark_notifications_read
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkNotificationsRead:
    """Tests for the mark_notifications_read tool."""

    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_single_notification(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        """Marks a single notification as read."""
        mock_service.mark_as_read = AsyncMock(return_value=True)

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        assert result["success"] is True
        mock_service.mark_as_read.assert_awaited_once_with("notif-1", FAKE_USER_ID)

    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_bulk_notifications(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        """Marks multiple notifications as read using bulk action."""
        mock_service.bulk_actions = AsyncMock(
            return_value={"notif-1": True, "notif-2": True}
        )

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1", "notif-2"],
        )

        assert result["success"] is True
        mock_service.bulk_actions.assert_awaited_once()

    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_ids_returns_error(
        self,
        mock_get_user: MagicMock,
    ) -> None:
        """Empty notification IDs list returns error."""
        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=[],
        )

        assert result["success"] is False
        assert "No notification IDs" in result["error"]

    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
    ) -> None:
        """Missing user returns auth error."""
        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config_no_user(),
            notification_ids=["notif-1"],
        )

        assert result["success"] is False
        assert result["error"] == "User authentication required"

    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        """Service exception returns error."""
        mock_service.mark_as_read = AsyncMock(side_effect=Exception("service down"))

        from app.agents.tools.notification_tool import mark_notifications_read

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        assert result["success"] is False
        assert "service down" in result["error"]
