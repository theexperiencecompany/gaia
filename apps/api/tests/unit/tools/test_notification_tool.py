"""Unit tests for app.agents.tools.notification_tool."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationContentView,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.models.notification.request_models import NotificationQuery
from app.models.user_models import UserDocument
from tests.helpers import captured_wide_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.notification_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    """The tool's own return value, minus the rate limiter's injected usage block."""
    return {key: value for key, value in result.items() if key != "_rate_limit_info"}


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
        """Returns notifications successfully."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)

        from app.agents.tools.notification_tool import get_notifications

        result = await get_notifications.coroutine(config=_make_config())

        assert result["notifications"] == [n.model_dump(mode="json") for n in notifications]
        assert "error" not in result
        mock_service.get_user_notifications.assert_awaited_once_with(
            FAKE_USER_ID,
            NotificationQuery(
                status=NotificationStatus.DELIVERED,
                notification_type=None,
                source=None,
                limit=50,
                offset=0,
            ),
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_every_filter_and_page_bound_reaches_the_query(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Each argument lands on the NotificationQuery handed to the service."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(return_value=[])

        from app.agents.tools.notification_tool import get_notifications

        await get_notifications.coroutine(
            config=_make_config(),
            status=NotificationStatus.ARCHIVED,
            notification_type=NotificationType.ERROR,
            source=NotificationSourceEnum.WORKFLOW_FAILED,
            limit=7,
            offset=13,
        )

        mock_service.get_user_notifications.assert_awaited_once_with(
            FAKE_USER_ID,
            NotificationQuery(
                status=NotificationStatus.ARCHIVED,
                notification_type=NotificationType.ERROR,
                source=NotificationSourceEnum.WORKFLOW_FAILED,
                limit=7,
                offset=13,
            ),
        )

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
        mock_service.get_user_notifications = AsyncMock(side_effect=Exception("DB error"))

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

        notif_calls = [c for c in writer.call_args_list if "notification_data" in c[0][0]]
        assert len(notif_calls) == 1
        assert notif_calls[0][0][0]["notification_data"]["notifications"] == [
            n.model_dump(mode="json") for n in notifications
        ]


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
    async def test_scans_the_first_hundred_under_the_status_filter(
        self,
        mock_get_user: MagicMock,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """The search reads one fixed window and filters it in process."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(return_value=[])

        from app.agents.tools.notification_tool import search_notifications

        await search_notifications.coroutine(
            config=_make_config(),
            query="deploy",
            status=NotificationStatus.ARCHIVED,
        )

        mock_service.get_user_notifications.assert_awaited_once_with(
            FAKE_USER_ID,
            NotificationQuery(status=NotificationStatus.ARCHIVED, limit=100, offset=0),
        )

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
        mock_service.bulk_actions = AsyncMock(return_value={"notif-1": True, "notif-2": True})

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


# ---------------------------------------------------------------------------
# Tests: send_urgent_alert
# ---------------------------------------------------------------------------

URGENT_TITLE = "Standup moved to 11am"
URGENT_MESSAGE = "Your 2pm standup is now at 11am. Move the client call."
SIGNAL_KIND = "meeting_moved"
BRIEFING_CHANNELS = ["inapp", "telegram"]
ALERT_NOTIFICATION_ID = "urgent-1"

#: A user whose ``created_at`` is a datetime, so a json-mode dump (an ISO
#: string) is distinguishable from a python-mode one (the datetime itself).
ALERT_USER = UserDocument(
    id=FAKE_USER_ID,
    email="user@example.com",
    created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
)


@dataclass
class _AlertSeams:
    """Every collaborator ``send_urgent_alert`` reaches through."""

    service: MagicMock
    user_repository: MagicMock
    resolve_channels: AsyncMock
    track: MagicMock


@contextmanager
def _alert_seams(
    *,
    user: UserDocument | None = ALERT_USER,
    channels: list[str] | None = None,
    create_notification: AsyncMock | None = None,
) -> Iterator[_AlertSeams]:
    """Patch the tool's seams; ``get_user_id_from_config`` stays real."""
    record = NotificationRecord(
        id=ALERT_NOTIFICATION_ID,
        user_id=FAKE_USER_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        original_request=NotificationRequest(
            user_id=FAKE_USER_ID,
            source=NotificationSourceEnum.AI_AGENT,
            content=NotificationContent(title=URGENT_TITLE, body=URGENT_MESSAGE),
        ),
    )
    seams = _AlertSeams(
        service=MagicMock(
            create_notification=create_notification or AsyncMock(return_value=record)
        ),
        user_repository=MagicMock(get=AsyncMock(return_value=user)),
        resolve_channels=AsyncMock(
            return_value=list(BRIEFING_CHANNELS if channels is None else channels)
        ),
        track=MagicMock(),
    )
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}.notification_service", seams.service))
        stack.enter_context(patch(f"{MODULE}.user_repository", seams.user_repository))
        stack.enter_context(patch(f"{MODULE}.resolve_briefing_channels", seams.resolve_channels))
        stack.enter_context(patch(f"{MODULE}.track", seams.track))
        yield seams


class TestSendUrgentAlert:
    """Tests for the send_urgent_alert tool."""

    async def test_sends_a_warning_on_every_briefing_channel(self) -> None:
        """The alert is a WARNING notification on the user's briefing channels."""
        from app.agents.tools.notification_tool import send_urgent_alert

        async with captured_wide_event() as event:
            with _alert_seams() as seams:
                result = await send_urgent_alert.coroutine(
                    config=_make_config(),
                    title=f"  {URGENT_TITLE}  ",
                    message=f"\t{URGENT_MESSAGE}\n",
                    signal_kind=SIGNAL_KIND,
                )

        assert _payload(result) == {
            "success": True,
            "notification_id": ALERT_NOTIFICATION_ID,
            "title": URGENT_TITLE,
            "message": URGENT_MESSAGE,
            "notification_type": "warning",
            "status": "sent",
            "delivered_channels": BRIEFING_CHANNELS,
        }
        seams.user_repository.get.assert_awaited_once_with(FAKE_USER_ID)
        seams.resolve_channels.assert_awaited_once_with(
            FAKE_USER_ID, ALERT_USER.model_dump(mode="json")
        )
        seams.track.assert_called_once_with(
            FAKE_USER_ID,
            "urgent_alert_sent",
            {"signal_kind": SIGNAL_KIND, "channels": BRIEFING_CHANNELS},
        )
        assert event["tool"] == {"name": "send_urgent_alert", "signal_kind": SIGNAL_KIND}
        assert event["notification"] == {
            "id": ALERT_NOTIFICATION_ID,
            "channels": BRIEFING_CHANNELS,
        }

    async def test_builds_the_notification_request_the_orchestrator_needs(self) -> None:
        """Source, type, channels, content and metadata are all pinned."""
        from app.agents.tools.notification_tool import send_urgent_alert

        with _alert_seams() as seams:
            await send_urgent_alert.coroutine(
                config=_make_config(),
                title=f"  {URGENT_TITLE}  ",
                message=f"\t{URGENT_MESSAGE}\n",
                signal_kind=SIGNAL_KIND,
            )

        (request,) = seams.service.create_notification.await_args.args
        assert request.user_id == FAKE_USER_ID
        assert request.source == NotificationSourceEnum.AI_AGENT
        assert request.type == NotificationType.WARNING
        assert request.channels == [ChannelConfig(channel_type=ch) for ch in BRIEFING_CHANNELS]
        assert request.content == NotificationContent(title=URGENT_TITLE, body=URGENT_MESSAGE)
        assert request.metadata == {
            "kind": "urgent_signal",
            "signal_kind": SIGNAL_KIND,
        }

    async def test_user_without_a_document_resolves_channels_from_no_profile(self) -> None:
        """A missing user document sends an empty profile, not a crash."""
        from app.agents.tools.notification_tool import send_urgent_alert

        with _alert_seams(user=None, channels=["inapp"]) as seams:
            result = await send_urgent_alert.coroutine(
                config=_make_config(),
                title=URGENT_TITLE,
                message=URGENT_MESSAGE,
                signal_kind=SIGNAL_KIND,
            )

        seams.resolve_channels.assert_awaited_once_with(FAKE_USER_ID, {})
        assert result["delivered_channels"] == ["inapp"]

    async def test_no_user_returns_auth_error(self) -> None:
        """Missing user_id refuses before any delivery work."""
        from app.agents.tools.notification_tool import send_urgent_alert

        with _alert_seams() as seams:
            result = await send_urgent_alert.coroutine(
                config=_make_config_no_user(),
                title=URGENT_TITLE,
                message=URGENT_MESSAGE,
                signal_kind=SIGNAL_KIND,
            )

        assert _payload(result) == {"error": "User authentication required", "success": False}
        seams.service.create_notification.assert_not_awaited()
        seams.user_repository.get.assert_not_awaited()

    @pytest.mark.parametrize(
        ("title", "message"),
        [
            ("   ", URGENT_MESSAGE),
            (URGENT_TITLE, "\n"),
            ("", ""),
        ],
        ids=["blank-title", "blank-message", "both-blank"],
    )
    async def test_blank_title_or_message_is_refused(self, title: str, message: str) -> None:
        """Either half missing refuses the alert; both halves are required."""
        from app.agents.tools.notification_tool import send_urgent_alert

        with _alert_seams() as seams:
            result = await send_urgent_alert.coroutine(
                config=_make_config(),
                title=title,
                message=message,
                signal_kind=SIGNAL_KIND,
            )

        assert _payload(result) == {
            "error": "Urgent alerts need a title and a message",
            "success": False,
        }
        seams.service.create_notification.assert_not_awaited()

    async def test_delivery_failure_returns_the_error_and_records_it(self) -> None:
        """A failed create surfaces the message and lands on the wide event."""
        from app.agents.tools.notification_tool import send_urgent_alert

        failing = AsyncMock(side_effect=RuntimeError("channel down"))
        async with captured_wide_event() as event:
            with _alert_seams(create_notification=failing):
                result = await send_urgent_alert.coroutine(
                    config=_make_config(),
                    title=URGENT_TITLE,
                    message=URGENT_MESSAGE,
                    signal_kind=SIGNAL_KIND,
                )

        assert _payload(result) == {"error": "channel down", "success": False}
        assert event["errors"][-1] == {
            "msg": f"{LogTag.TOOL} Error sending urgent alert",
            "error_type": "RuntimeError",
            "error": "channel down",
        }
