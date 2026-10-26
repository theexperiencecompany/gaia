"""Unit tests for app.agents.tools.notification_tool."""

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools import notification_tool as notification_tool_module
from app.agents.tools.notification_tool import (
    get_notification_count,
    get_notification_preferences,
    get_notifications,
    mark_notifications_read,
    search_notifications,
    send_notification,
)
from app.constants.notifications import NOTIFICATION_CHANNEL_TYPES
from app.helpers.agent_helpers import AgentIdentity, AgentThread, AgentTurn, build_agent_config
from app.models.agent_models import RunUserMissingError
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationContentView,
    NotificationListFilters,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.services.delivery.chat_channel import ChatChannel, InApp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.notification_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict naming the run user."""
    return {"configurable": {"user_id": user_id}, "metadata": {"user_id": user_id}}


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


# ---------------------------------------------------------------------------
# Tests: get_notifications
# ---------------------------------------------------------------------------


class TestGetNotifications:
    """Tests for the get_notifications tool."""

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_happy_path(
        self,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Returns notifications successfully."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)

        result = await get_notifications.coroutine(
            config=_make_config(),
            status=NotificationStatus.READ,
            notification_type=NotificationType.WARNING,
            source=NotificationSourceEnum.AI_REMINDER,
            limit=7,
            offset=3,
        )

        assert result["notifications"] == [n.model_dump(mode="json") for n in notifications]
        assert "error" not in result
        # Every filter the model passed reaches the service; a dropped one
        # silently widens what the user is shown.
        mock_service.get_user_notifications.assert_awaited_once_with(
            FAKE_USER_ID,
            filters=NotificationListFilters(
                status=NotificationStatus.READ,
                notification_type=NotificationType.WARNING,
                source=NotificationSourceEnum.AI_REMINDER,
                limit=7,
                offset=3,
            ),
        )

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_service_error(
        self,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Service exception returns error response."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(side_effect=Exception("DB error"))

        result = await get_notifications.coroutine(config=_make_config())

        assert "DB error" in result["error"]
        assert result["notifications"] == []

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_forwards_all_filters(
        self,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Every argument reaches get_user_notifications as the matching filter field."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(return_value=[])

        await get_notifications.coroutine(
            config=_make_config(),
            status=NotificationStatus.READ,
            notification_type=NotificationType.WARNING,
            source=NotificationSourceEnum.WORKFLOW_COMPLETED,
            limit=7,
            offset=3,
        )

        call = mock_service.get_user_notifications.await_args
        assert call.args[0] == FAKE_USER_ID
        filters = call.kwargs["filters"]
        assert filters.status == NotificationStatus.READ
        assert filters.notification_type == NotificationType.WARNING
        assert filters.source == NotificationSourceEnum.WORKFLOW_COMPLETED
        assert filters.limit == 7
        assert filters.offset == 3

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_streams_notification_data(
        self,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Notification data is streamed to frontend."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        notifications = [_make_notification()]
        mock_service.get_user_notifications = AsyncMock(return_value=notifications)

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

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_happy_path_title_match(
        self,
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

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="meeting",
            status=NotificationStatus.READ,
        )

        assert len(result["notifications"]) == 1
        assert result["notifications"][0]["content"]["title"] == "Meeting reminder"
        # The search scans one page of a hundred under the caller's status filter.
        mock_service.get_user_notifications.assert_awaited_once_with(
            FAKE_USER_ID, filters=NotificationListFilters(status=NotificationStatus.READ, limit=100)
        )

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_search_body_match(
        self,
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

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="deployment",
        )

        assert len(result["notifications"]) == 1

    @patch(f"{MODULE}.current_stream_writer")
    async def test_empty_query_returns_error(
        self,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty search query returns error."""
        mock_writer_factory.return_value = _writer_mock()

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="   ",
        )

        assert "error" in result
        assert "cannot be empty" in result["error"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_limit_applied(
        self,
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

        result = await search_notifications.coroutine(
            config=_make_config(),
            query="test",
            limit=3,
        )

        assert len(result["notifications"]) == 3

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_forwards_fetch_filters(
        self,
        mock_service: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Fetch pulls the status the caller asked for, capped at 100 rows."""
        mock_writer_factory.return_value = _writer_mock()
        mock_service.get_user_notifications = AsyncMock(return_value=[])

        await search_notifications.coroutine(
            config=_make_config(),
            query="test",
            status=NotificationStatus.READ,
        )

        call = mock_service.get_user_notifications.await_args
        assert call.args[0] == FAKE_USER_ID
        filters = call.kwargs["filters"]
        assert filters.status == NotificationStatus.READ
        assert filters.limit == 100


# ---------------------------------------------------------------------------
# Tests: get_notification_count
# ---------------------------------------------------------------------------


class TestGetNotificationCount:
    """Tests for the get_notification_count tool."""

    @patch(f"{MODULE}.notification_service")
    async def test_happy_path(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Returns count of notifications."""
        mock_service.get_user_notifications_count = AsyncMock(return_value=5)

        result = await get_notification_count.coroutine(config=_make_config())

        assert result["count"] == 5

    @patch(f"{MODULE}.notification_service")
    async def test_service_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Service error returns count 0."""
        mock_service.get_user_notifications_count = AsyncMock(
            side_effect=Exception("connection lost")
        )

        result = await get_notification_count.coroutine(config=_make_config())

        assert result["count"] == 0
        assert "connection lost" in result["error"]


# ---------------------------------------------------------------------------
# Tests: mark_notifications_read
# ---------------------------------------------------------------------------


class TestMarkNotificationsRead:
    """Tests for the mark_notifications_read tool."""

    @patch(f"{MODULE}.notification_service")
    async def test_single_notification(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Marks a single notification as read."""
        mock_service.mark_as_read = AsyncMock(return_value=True)

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        assert result["success"] is True
        mock_service.mark_as_read.assert_awaited_once_with("notif-1", FAKE_USER_ID)

    @patch(f"{MODULE}.notification_service")
    async def test_bulk_notifications(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Marks multiple notifications as read using bulk action."""
        mock_service.bulk_actions = AsyncMock(return_value={"notif-1": True, "notif-2": True})

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1", "notif-2"],
        )

        assert result["success"] is True
        mock_service.bulk_actions.assert_awaited_once()

    async def test_empty_ids_returns_error(
        self,
    ) -> None:
        """Empty notification IDs list returns error."""
        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=[],
        )

        assert result["success"] is False
        assert "No notification IDs" in result["error"]

    @patch(f"{MODULE}.notification_service")
    async def test_service_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Service exception returns error."""
        mock_service.mark_as_read = AsyncMock(side_effect=Exception("service down"))

        result = await mark_notifications_read.coroutine(
            config=_make_config(),
            notification_ids=["notif-1"],
        )

        assert result["success"] is False
        assert "service down" in result["error"]


# ---------------------------------------------------------------------------
# Tests: send_notification channel validation
# ---------------------------------------------------------------------------


class TestSendNotificationChannels:
    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_no_channel_named_goes_where_the_user_is_reachable_now(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
        )
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        result = await send_notification.coroutine(
            config=_chat_run_config("web"), message="Build done", title="Build"
        )

        mock_resolve.assert_awaited_once_with(FAKE_USER_ID)
        assert _requested_channels(mock_service) == ["telegram"]
        assert result["delivered_channels"] == ["telegram"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_no_chat_app_linked_means_in_app(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="no_chat_app")
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_make_config(), message="Build done", title="Build", channels=[]
        )

        assert _requested_channels(mock_service) == ["inapp"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_a_workflow_run_with_no_channel_folds_into_its_own_result(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="active_in_app")

        result = await send_notification.coroutine(
            config=_chat_run_config(None, workflow_id="wf-1", execution_mode="background"),
            message="Build done",
            title="Build",
        )

        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "inapp"

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_a_workflow_run_without_completion_delivery_still_notifies(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="active_in_app")
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)
        config = _chat_run_config(None, workflow_id="wf-1", execution_mode="background")
        config["configurable"]["workflow_notify_on_completion"] = False

        await send_notification.coroutine(config=config, message="Build done", title="Build")

        assert _requested_channels(mock_service) == ["inapp"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.todo_repository")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_a_tracked_todo_run_with_no_channel_folds_into_its_own_result(
        self,
        mock_resolve: AsyncMock,
        mock_service: MagicMock,
        mock_todos: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
        )
        mock_todos.get_by_id = AsyncMock(return_value=MagicMock(notify_on_run=True))

        result = await send_notification.coroutine(
            config=_chat_run_config(None, active_todo_id="todo-1", execution_mode="background"),
            message="Found it",
            title="Todo",
        )

        mock_todos.get_by_id.assert_awaited_once_with("todo-1")
        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "telegram"

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.todo_repository")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_a_silent_tracked_todo_run_still_notifies(
        self,
        mock_resolve: AsyncMock,
        mock_service: MagicMock,
        mock_todos: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="active_in_app")
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)
        mock_todos.get_by_id = AsyncMock(return_value=MagicMock(notify_on_run=False))

        await send_notification.coroutine(
            config=_chat_run_config(None, active_todo_id="todo-1", execution_mode="background"),
            message="Found it",
            title="Todo",
        )

        assert _requested_channels(mock_service) == ["inapp"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_a_background_run_naming_a_channel_still_sends_it(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_chat_run_config(None, workflow_id="wf-1", execution_mode="background"),
            message="Urgent",
            title="Urgent",
            channels=["whatsapp"],
        )

        assert _requested_channels(mock_service) == ["whatsapp"]
        mock_resolve.assert_not_called()

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.todo_repository")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_an_interactive_run_bound_to_a_todo_is_not_treated_as_delivered(
        self,
        mock_resolve: AsyncMock,
        mock_service: MagicMock,
        mock_todos: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="no_chat_app")
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_chat_run_config(None, active_todo_id="todo-1", execution_mode="interactive"),
            message="Hi",
            title="Hi",
        )

        mock_todos.get_by_id.assert_not_called()
        assert _requested_channels(mock_service) == ["inapp"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_an_unnamed_channel_from_a_web_chat_folds_into_the_reply(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """The user is in the app and the reply lands there: a web run notifies nobody else."""
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = InApp(reason="active_in_app")

        result = await send_notification.coroutine(
            config=_chat_run_config("web"), message="Done", title="Done"
        )

        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "inapp"

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    @patch(f"{MODULE}.resolve_proactive_target", new_callable=AsyncMock)
    async def test_an_unnamed_channel_on_the_chat_the_user_is_in_folds_into_the_reply(
        self, mock_resolve: AsyncMock, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_resolve.return_value = ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
        )

        result = await send_notification.coroutine(
            config=_chat_run_config("telegram"), message="Done", title="Done"
        )

        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "telegram"

    @patch(f"{MODULE}.notification_service")
    async def test_unknown_channels_are_named_and_valid_ones_listed(
        self,
        mock_service: MagicMock,
    ) -> None:
        result = await send_notification.coroutine(
            config=_make_config(),
            message="Build done",
            title="Build",
            channels=["telegram", "pager", "imessage", "fax"],
        )

        assert result["success"] is False
        unknown, valid = result["error"].split(" Valid channels: ")
        assert unknown == "Unknown channel(s): pager, fax."
        assert valid == f"{', '.join(NOTIFICATION_CHANNEL_TYPES)}."
        mock_service.create_notification.assert_not_called()


@patch(f"{MODULE}.current_stream_writer")
@patch(f"{MODULE}.notification_service")
async def test_a_sent_notification_is_streamed_as_the_result_it_returns(
    mock_service: MagicMock, mock_writer_factory: MagicMock
) -> None:
    async def deliver(request: NotificationRequest) -> NotificationRecord:
        return NotificationRecord(
            id="notif-9",
            user_id=FAKE_USER_ID,
            status=NotificationStatus.DELIVERED,
            created_at="2026-01-01T00:00:00+00:00",
            channels=[
                ChannelDeliveryStatus(channel_type="inapp", status=NotificationStatus.DELIVERED),
                ChannelDeliveryStatus(
                    channel_type="telegram", status=NotificationStatus.DELIVERED, skipped=True
                ),
            ],
            original_request=request,
        )

    writer = _writer_mock()
    mock_writer_factory.return_value = writer
    mock_service.create_notification = AsyncMock(side_effect=deliver)

    result = await send_notification.coroutine(
        config=_make_config(),
        message=" Build done ",
        title=" Build ",
        channels=["inapp", "telegram"],
    )

    # The rate-limiting decorator adds its own _rate_limit_info key.
    assert {k: v for k, v in result.items() if k != "_rate_limit_info"} == {
        "success": True,
        "notification_id": "notif-9",
        "title": "Build",
        "message": "Build done",
        "notification_type": NotificationType.INFO.value,
        "status": NotificationStatus.DELIVERED.value,
        "delivered_channels": ["inapp"],
    }
    writer.assert_called_once_with({"send_notification_data": result})


def _chat_run_config(
    source: str | None, **extra: str | bool
) -> dict[str, dict[str, str | bool | None]]:
    """Build a run config the way build_agent_config writes one for a turn from source."""
    configurable: dict[str, str | bool | None] = {
        "user_id": FAKE_USER_ID,
        "conversation_id": "conv-1",
        "conversation_source": source,
        **extra,
    }
    return {"configurable": configurable, "metadata": {"user_id": FAKE_USER_ID}}


async def _delivered_on_every_channel(request: NotificationRequest) -> NotificationRecord:
    return NotificationRecord(
        id="notif-7",
        user_id=FAKE_USER_ID,
        status=NotificationStatus.DELIVERED,
        created_at="2026-01-01T00:00:00+00:00",
        channels=[
            ChannelDeliveryStatus(channel_type=ch.channel_type, status=NotificationStatus.DELIVERED)
            for ch in request.channels
        ],
        original_request=request,
    )


def _requested_channels(mock_service: MagicMock) -> list[str]:
    request: NotificationRequest = mock_service.create_notification.await_args.args[0]
    return [ch.channel_type for ch in request.channels]


class TestSendNotificationNeverDuplicatesTheReply:
    """A run started from a bot chat already replies into that chat."""

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_notifying_the_chat_the_user_is_in_sends_nothing_and_says_why(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        result = await send_notification.coroutine(
            config=_chat_run_config("telegram"),
            message="Your flight is booked",
            title="Flight",
            channels=["telegram"],
        )

        mock_service.create_notification.assert_not_called()
        writer.assert_not_called()
        assert {k: v for k, v in result.items() if k != "_rate_limit_info"} == {
            "success": True,
            "delivered_channels": [],
            "delivered_via_conversation": "telegram",
            "note": (
                "Your result is delivered on Telegram automatically. Put the update "
                "in your result instead of notifying."
            ),
        }

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_another_channel_the_user_named_is_still_sent(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        result = await send_notification.coroutine(
            config=_chat_run_config("telegram"),
            message="Your flight is booked",
            title="Flight",
            channels=["telegram", "whatsapp"],
        )

        assert _requested_channels(mock_service) == ["whatsapp"]
        assert result["success"] is True
        assert result["delivered_channels"] == ["whatsapp"]

    @pytest.mark.parametrize("source", ["web", "mobile", "desktop"])
    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_an_in_app_notification_from_an_app_chat_folds_into_the_reply(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock, source: str
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()

        result = await send_notification.coroutine(
            config=_chat_run_config(source),
            message="Your flight is booked",
            title="Flight",
            channels=["inapp"],
        )

        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "inapp"
        assert result["note"].startswith("Your result is delivered in the GAIA app")

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_a_web_chat_run_notifies_telegram_as_asked(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_chat_run_config("web"),
            message="Your flight is booked",
            title="Flight",
            channels=["telegram"],
        )

        assert _requested_channels(mock_service) == ["telegram"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_a_web_chat_run_drops_only_the_in_app_copy_of_a_mixed_list(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_chat_run_config("web"),
            message="Your flight is booked",
            title="Flight",
            channels=["inapp", "telegram"],
        )

        assert _requested_channels(mock_service) == ["telegram"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_a_workflow_run_notifies_telegram_as_asked(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        # A workflow fire carries no conversation_source (workflow_tasks passes none).
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)

        await send_notification.coroutine(
            config=_chat_run_config(None, workflow_id="wf-1", execution_mode="background"),
            message="An urgent email arrived",
            title="Urgent email",
            channels=["telegram"],
        )

        assert _requested_channels(mock_service) == ["telegram"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_a_bot_run_without_a_conversation_is_not_folded(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)
        config = _chat_run_config("telegram")
        config["configurable"]["conversation_id"] = None

        await send_notification.coroutine(
            config=config, message="Done", title="Done", channels=["telegram"]
        )

        assert _requested_channels(mock_service) == ["telegram"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.notification_service")
    async def test_the_executor_a_telegram_turn_spawns_folds_through_its_inherited_config(
        self, mock_service: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        # The bug's real path: comms on Telegram -> call_executor -> the executor's own
        # config, built the way prepare_executor_execution builds it (no source of its own).
        mock_writer_factory.return_value = _writer_mock()
        mock_service.create_notification = AsyncMock(side_effect=_delivered_on_every_channel)
        user = {"user_id": FAKE_USER_ID, "email": "user@example.com", "name": "User"}
        comms = await build_agent_config(
            identity=AgentIdentity(conversation_id="conv-1", user=user, agent_name="comms_agent"),
            turn=AgentTurn(source="telegram"),
        )
        executor = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=comms["configurable"]["thread_id"],
                user=user,
                agent_name="executor_agent",
            ),
            thread=AgentThread(
                thread_id=f"executor_{comms['configurable']['thread_id']}",
                base_configurable=comms["configurable"],
                subagent_id="executor_agent",
            ),
        )

        result = await send_notification.coroutine(
            config=executor, message="Done", title="Done", channels=["telegram"]
        )

        mock_service.create_notification.assert_not_called()
        assert result["delivered_via_conversation"] == "telegram"


@patch(f"{MODULE}.fetch_channel_preferences", new_callable=AsyncMock)
async def test_the_run_users_channel_preferences_are_read(mock_fetch: AsyncMock) -> None:
    mock_fetch.return_value = {"email": False}

    result = await get_notification_preferences.coroutine(config=_make_config())

    mock_fetch.assert_awaited_once_with(FAKE_USER_ID)
    assert result["enabled_channels"] == ["inapp"]


def _required_args(tool: Any) -> dict[str, None]:
    """Bind every required non-config parameter; the user check runs before any is read."""
    params = inspect.signature(tool.coroutine).parameters.values()
    return {
        p.name: None for p in params if p.name != "config" and p.default is inspect.Parameter.empty
    }


@pytest.mark.parametrize("tool", notification_tool_module.tools, ids=lambda t: t.name)
async def test_a_run_with_no_user_raises_instead_of_returning_a_tool_error(tool: Any) -> None:
    with pytest.raises(RunUserMissingError):
        await tool.coroutine(config={"configurable": {}}, **_required_args(tool))
