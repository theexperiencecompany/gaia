"""Unit tests for notification channel adapters (inapp, discord, telegram, external base)."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.notifications import (
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_TELEGRAM,
)
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    ChannelDeliveryStatus,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    RedirectConfig,
)
from app.utils.notification.channels.discord import DiscordChannelAdapter
from app.utils.notification.channels.inapp import InAppChannelAdapter
from app.utils.notification.channels.telegram import TelegramChannelAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SENTINEL = object()


def _make_request(
    channels: Any = _SENTINEL,
    title: str = "Test Title",
    body: str = "Test body text",
    actions: Optional[List[NotificationAction]] = None,
    rich_content: Optional[Dict[str, Any]] = None,
) -> NotificationRequest:
    resolved_channels: List[ChannelConfig]
    if channels is _SENTINEL:
        resolved_channels = [ChannelConfig(channel_type="inapp", enabled=True)]
    else:
        resolved_channels = channels
    return NotificationRequest(
        id="notif-1",
        user_id="user-1",
        source=NotificationSourceEnum.AI_TODO_ADDED,
        type=NotificationType.INFO,
        priority=2,
        channels=resolved_channels,
        content=NotificationContent(
            title=title,
            body=body,
            actions=actions,
            rich_content=rich_content,
        ),
        metadata={"key": "value"},
    )


def _make_redirect_action(
    label: str = "View",
    url: str = "/test",
) -> NotificationAction:
    return NotificationAction(
        type=ActionType.REDIRECT,
        label=label,
        style=ActionStyle.PRIMARY,
        config=ActionConfig(redirect=RedirectConfig(url=url, open_in_new_tab=False)),
    )


# ========================================================================
# ChannelAdapter base class helpers
# ========================================================================


@pytest.mark.unit
class TestChannelAdapterBaseHelpers:
    """Tests for the ChannelAdapter base class status helpers."""

    def test_success_helper(self) -> None:
        """_success returns DELIVERED status with delivered_at set."""
        adapter = InAppChannelAdapter()
        status = adapter._success()
        assert status.channel_type == CHANNEL_TYPE_INAPP
        assert status.status == NotificationStatus.DELIVERED
        assert status.delivered_at is not None

    def test_error_helper(self) -> None:
        """_error returns FAILED status with the error message."""
        adapter = InAppChannelAdapter()
        status = adapter._error("something broke")
        assert status.channel_type == CHANNEL_TYPE_INAPP
        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "something broke"
        assert status.skipped is False

    def test_skipped_helper(self) -> None:
        """_skipped returns FAILED status with skipped=True."""
        adapter = InAppChannelAdapter()
        status = adapter._skipped("not linked")
        assert status.channel_type == CHANNEL_TYPE_INAPP
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True
        assert status.error_message == "not linked"


# ========================================================================
# InAppChannelAdapter
# ========================================================================


@pytest.mark.unit
class TestInAppChannelAdapterProperties:
    """Tests for InAppChannelAdapter basic properties."""

    def test_channel_type(self) -> None:
        adapter = InAppChannelAdapter()
        assert adapter.channel_type == CHANNEL_TYPE_INAPP

    def test_can_handle_with_inapp_channel(self) -> None:
        """Returns True when the request includes an inapp channel."""
        adapter = InAppChannelAdapter()
        request = _make_request(
            channels=[ChannelConfig(channel_type="inapp", enabled=True)]
        )
        assert adapter.can_handle(request) is True

    def test_can_handle_without_inapp_channel(self) -> None:
        """Returns False when no inapp channel is present."""
        adapter = InAppChannelAdapter()
        request = _make_request(
            channels=[ChannelConfig(channel_type="telegram", enabled=True)]
        )
        assert adapter.can_handle(request) is False

    def test_can_handle_empty_channels(self) -> None:
        """Returns False when channels list is empty."""
        adapter = InAppChannelAdapter()
        request = _make_request(channels=[])
        assert adapter.can_handle(request) is False


@pytest.mark.unit
class TestInAppTransform:
    """Tests for InAppChannelAdapter.transform."""

    async def test_basic_transform(self) -> None:
        """Transforms notification content into the in-app payload format."""
        adapter = InAppChannelAdapter()
        request = _make_request(title="Hello", body="World")
        content = await adapter.transform(request)

        assert content["id"] == request.id
        assert content["title"] == "Hello"
        assert content["body"] == "World"
        assert content["type"] == NotificationType.INFO
        assert content["priority"] == 2
        assert content["metadata"] == {"key": "value"}
        assert "created_at" in content

    async def test_transform_with_actions(self) -> None:
        """Actions are included in the transformed payload."""
        action = _make_redirect_action(label="Go", url="/go")
        adapter = InAppChannelAdapter()
        request = _make_request(actions=[action])
        content = await adapter.transform(request)

        assert len(content["actions"]) == 1
        assert content["actions"][0]["label"] == "Go"
        assert content["actions"][0]["type"] == ActionType.REDIRECT

    async def test_transform_without_actions(self) -> None:
        """When content.actions is None, actions list is empty."""
        adapter = InAppChannelAdapter()
        request = _make_request(actions=None)
        content = await adapter.transform(request)

        assert content["actions"] == []


@pytest.mark.unit
class TestInAppDeliver:
    """Tests for InAppChannelAdapter.deliver."""

    async def test_successful_delivery(self) -> None:
        """Broadcasts via websocket and returns success status."""
        adapter = InAppChannelAdapter()
        content = {"id": "notif-1", "title": "Test"}

        with patch("app.utils.notification.channels.inapp.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            status = await adapter.deliver(content, "user-1")

        assert status.status == NotificationStatus.DELIVERED
        assert status.channel_type == CHANNEL_TYPE_INAPP
        ws.broadcast_to_user.assert_awaited_once()
        payload = ws.broadcast_to_user.call_args[0][1]
        assert payload["type"] == "notification.new"
        assert payload["notification"] is content

    async def test_delivery_failure(self) -> None:
        """Returns error status when websocket broadcast raises."""
        adapter = InAppChannelAdapter()
        content = {"id": "notif-1", "title": "Test"}

        with patch("app.utils.notification.channels.inapp.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("ws down"))
            status = await adapter.deliver(content, "user-1")

        assert status.status == NotificationStatus.FAILED
        assert "ws down" in (status.error_message or "")


# ========================================================================
# ExternalPlatformAdapter (tested via concrete Discord adapter)
# ========================================================================


@pytest.mark.unit
class TestExternalPlatformAdapterCanHandle:
    """ExternalPlatformAdapter.can_handle always returns True."""

    def test_can_handle_always_true(self) -> None:
        adapter = DiscordChannelAdapter()
        request = _make_request(channels=[])
        assert adapter.can_handle(request) is True


@pytest.mark.unit
class TestExternalPlatformSplitText:
    """Tests for ExternalPlatformAdapter._split_text."""

    def test_text_under_limit_returns_single(self) -> None:
        adapter = DiscordChannelAdapter()
        result = adapter._split_text("short text", 100)
        assert result == ["short text"]

    def test_text_exactly_at_limit(self) -> None:
        adapter = DiscordChannelAdapter()
        text = "a" * 100
        result = adapter._split_text(text, 100)
        assert result == [text]

    def test_text_over_limit_splits_at_newline(self) -> None:
        adapter = DiscordChannelAdapter()
        line1 = "a" * 50
        line2 = "b" * 50
        text = f"{line1}\n{line2}"
        result = adapter._split_text(text, 55)
        assert len(result) == 2
        assert result[0] == line1
        assert result[1] == line2

    def test_text_over_limit_no_newline_splits_at_limit(self) -> None:
        adapter = DiscordChannelAdapter()
        text = "a" * 200
        result = adapter._split_text(text, 100)
        assert len(result) == 2
        assert result[0] == "a" * 100
        assert result[1] == "a" * 100

    def test_multiple_splits(self) -> None:
        adapter = DiscordChannelAdapter()
        text = "line1\nline2\nline3\nline4"
        result = adapter._split_text(text, 12)
        # Each "lineN" is 5 chars + newline boundary handling
        assert len(result) >= 2
        rejoined = "\n".join(result)
        for part in ["line1", "line2", "line3", "line4"]:
            assert part in rejoined


@pytest.mark.unit
class TestExternalPlatformTransform:
    """Tests for ExternalPlatformAdapter.transform (via DiscordChannelAdapter)."""

    async def test_standard_message_format(self) -> None:
        """Standard message is formatted with bold title."""
        adapter = DiscordChannelAdapter()
        request = _make_request(title="My Title", body="My body")

        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter.transform(request)

        assert "**My Title**" in content["text"]
        assert "My body" in content["text"]

    async def test_standard_message_without_title(self) -> None:
        """When title is empty, body alone is used."""
        adapter = DiscordChannelAdapter()
        request = _make_request(title="", body="just body")

        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter.transform(request)

        assert content["text"] == "just body"

    async def test_redirect_actions_appended_as_links(self) -> None:
        """Redirect actions are appended as markdown links."""
        action = _make_redirect_action(label="View Task", url="/todos/1")
        adapter = DiscordChannelAdapter()
        request = _make_request(title="Task", body="details", actions=[action])

        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter.transform(request)

        assert "[View Task](https://app.example.com/todos/1)" in content["text"]

    async def test_workflow_execution_rich_content(self) -> None:
        """Rich content with type=workflow_execution returns workflow format."""
        adapter = DiscordChannelAdapter()
        request = _make_request(
            title="Workflow Done",
            body="Completed in 30s",
            rich_content={
                "type": "workflow_execution",
                "messages": ["Step 1 result", "Step 2 result"],
                "conversation_id": "conv-123",
            },
        )

        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter.transform(request)

        assert content["type"] == "workflow_messages"
        assert "Workflow Done" in content["header"]
        assert len(content["messages"]) == 2
        assert "conv-123" in content["footer"]

    async def test_workflow_no_conversation_id_empty_footer(self) -> None:
        """Workflow content without conversation_id yields empty footer."""
        adapter = DiscordChannelAdapter()
        request = _make_request(
            title="WF",
            body="Done",
            rich_content={
                "type": "workflow_execution",
                "messages": [],
                "conversation_id": "",
            },
        )

        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter.transform(request)

        assert content["footer"] == ""


@pytest.mark.unit
class TestExternalPlatformGetContext:
    """Tests for ExternalPlatformAdapter._get_platform_context."""

    async def test_platform_not_linked(self) -> None:
        """Returns skipped status when platform is not linked."""
        adapter = DiscordChannelAdapter()

        with patch(
            "app.utils.notification.channels.external.PlatformLinkService"
        ) as svc:
            svc.get_linked_platforms = AsyncMock(return_value={})
            ctx, err = await adapter._get_platform_context("user-1")

        assert ctx is None
        assert err is not None
        assert err.skipped is True
        assert "not linked" in (err.error_message or "")

    async def test_platform_user_id_missing(self) -> None:
        """Returns skipped when linked but platformUserId is absent."""
        adapter = DiscordChannelAdapter()

        with patch(
            "app.utils.notification.channels.external.PlatformLinkService"
        ) as svc:
            svc.get_linked_platforms = AsyncMock(
                return_value={"discord": {"platform": "discord"}}
            )
            ctx, err = await adapter._get_platform_context("user-1")

        assert ctx is None
        assert err is not None
        assert err.skipped is True
        assert "user id missing" in (err.error_message or "")

    async def test_bot_token_not_configured(self) -> None:
        """Returns skipped when bot token is None."""
        adapter = DiscordChannelAdapter()

        with (
            patch(
                "app.utils.notification.channels.external.PlatformLinkService"
            ) as svc,
            patch.object(adapter, "_get_bot_token", return_value=None),
        ):
            svc.get_linked_platforms = AsyncMock(
                return_value={
                    "discord": {
                        "platform": "discord",
                        "platformUserId": "12345",
                    }
                }
            )
            ctx, err = await adapter._get_platform_context("user-1")

        assert ctx is None
        assert err is not None
        assert "bot token" in (err.error_message or "").lower()

    async def test_successful_context(self) -> None:
        """Returns context dict with platform_user_id and token."""
        adapter = DiscordChannelAdapter()

        with (
            patch(
                "app.utils.notification.channels.external.PlatformLinkService"
            ) as svc,
            patch("app.utils.notification.channels.discord.settings") as mock_settings,
        ):
            mock_settings.DISCORD_BOT_TOKEN = "bot-token-123"
            svc.get_linked_platforms = AsyncMock(
                return_value={
                    "discord": {
                        "platform": "discord",
                        "platformUserId": "12345",
                    }
                }
            )
            ctx, err = await adapter._get_platform_context("user-1")

        assert err is None
        assert ctx is not None
        assert ctx["platform_user_id"] == "12345"
        assert ctx["token"] == "bot-token-123"


@pytest.mark.unit
class TestExternalPlatformDeliverContent:
    """Tests for ExternalPlatformAdapter._deliver_content."""

    async def test_standard_message_success(self) -> None:
        """Single text message delivered successfully."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value=None)
        content = {"text": "Hello, world!"}

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.DELIVERED
        send_fn.assert_awaited_once_with("Hello, world!")

    async def test_standard_message_empty_text(self) -> None:
        """Empty text returns error status."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock()
        content = {"text": ""}

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED
        assert "empty text" in (status.error_message or "").lower()
        send_fn.assert_not_awaited()

    async def test_standard_message_whitespace_only(self) -> None:
        """Whitespace-only text returns error status."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock()
        content = {"text": "   \n  "}

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED

    async def test_standard_message_non_string_text(self) -> None:
        """Non-string text field returns error status."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock()
        content = {"text": 12345}

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED

    async def test_standard_message_send_error(self) -> None:
        """send_fn returning error string yields FAILED status."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value="rate limited")
        content = {"text": "hello"}

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED
        assert "rate limited" in (status.error_message or "")

    async def test_workflow_messages_success(self) -> None:
        """Workflow content with header, messages, and footer all delivered."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value=None)
        content = {
            "type": "workflow_messages",
            "header": "Workflow Complete",
            "messages": ["Result 1", "Result 2"],
            "footer": "View more",
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.DELIVERED
        # header + 2 messages + footer = 4 calls
        assert send_fn.await_count == 4

    async def test_workflow_header_error(self) -> None:
        """Workflow header error returns FAILED immediately."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value="header send failed")
        content = {
            "type": "workflow_messages",
            "header": "Header text",
            "messages": ["msg"],
            "footer": "",
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED
        assert "header" in (status.error_message or "").lower()
        # Should stop after header failure, not attempt messages
        assert send_fn.await_count == 1

    async def test_workflow_message_error(self) -> None:
        """Workflow message error returns FAILED."""
        adapter = DiscordChannelAdapter()
        call_count = 0

        async def side_effect(text: str) -> Optional[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # fail on second call (first message)
                return "message send failed"
            return None

        send_fn = AsyncMock(side_effect=side_effect)
        content = {
            "type": "workflow_messages",
            "header": "OK header",
            "messages": ["msg1"],
            "footer": "footer",
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED
        assert "message" in (status.error_message or "").lower()

    async def test_workflow_footer_error(self) -> None:
        """Workflow footer error returns FAILED."""
        adapter = DiscordChannelAdapter()
        call_count = 0

        async def side_effect(text: str) -> Optional[str]:
            nonlocal call_count
            call_count += 1
            # Last call is footer — fail it
            if call_count == 3:
                return "footer error"
            return None

        send_fn = AsyncMock(side_effect=side_effect)
        content = {
            "type": "workflow_messages",
            "header": "H",
            "messages": ["M"],
            "footer": "F",
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.FAILED
        assert "footer" in (status.error_message or "").lower()

    async def test_workflow_no_header_no_footer(self) -> None:
        """Workflow with empty header/footer skips them."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value=None)
        content = {
            "type": "workflow_messages",
            "header": "",
            "messages": ["msg1"],
            "footer": "",
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.DELIVERED
        # Only the message is sent (empty header/footer are falsy)
        assert send_fn.await_count == 1

    async def test_workflow_long_message_split(self) -> None:
        """Long workflow messages are split by _split_text."""
        adapter = DiscordChannelAdapter()
        send_fn = AsyncMock(return_value=None)
        # Create a message longer than MAX_MESSAGE_LENGTH (2000 for Discord)
        long_msg = "word " * 500  # ~2500 chars
        content = {
            "type": "workflow_messages",
            "messages": [long_msg],
        }

        status = await adapter._deliver_content(send_fn, content)

        assert status.status == NotificationStatus.DELIVERED
        # Should have been split into multiple chunks
        assert send_fn.await_count >= 2


# ========================================================================
# ExternalPlatformAdapter.deliver (full flow)
# ========================================================================


@pytest.mark.unit
class TestExternalPlatformDeliver:
    """Tests for the full ExternalPlatformAdapter.deliver flow."""

    async def test_deliver_skipped_when_not_linked(self) -> None:
        """Returns skipped status when platform context is not available."""
        adapter = DiscordChannelAdapter()

        with patch(
            "app.utils.notification.channels.external.PlatformLinkService"
        ) as svc:
            svc.get_linked_platforms = AsyncMock(return_value={})
            status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.skipped is True
        assert status.status == NotificationStatus.FAILED

    async def test_deliver_setup_sender_error(self) -> None:
        """Returns error when _setup_sender fails."""
        adapter = DiscordChannelAdapter()

        setup_err = ChannelDeliveryStatus(
            channel_type="discord",
            status=NotificationStatus.FAILED,
            error_message="DM channel error",
        )

        with (
            patch.object(
                adapter,
                "_get_platform_context",
                new_callable=AsyncMock,
                return_value=(
                    {"platform_user_id": "12345", "token": "bot-token"},
                    None,
                ),
            ),
            patch(
                "app.utils.notification.channels.external.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            with patch.object(
                adapter,
                "_setup_sender",
                new_callable=AsyncMock,
                return_value=(None, setup_err),
            ):
                status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.status == NotificationStatus.FAILED
        assert "DM channel error" in (status.error_message or "")

    async def test_deliver_exception_returns_error(self) -> None:
        """An unexpected exception during deliver returns error status."""
        adapter = DiscordChannelAdapter()

        with patch.object(
            adapter,
            "_get_platform_context",
            new_callable=AsyncMock,
            return_value=(
                {"platform_user_id": "12345", "token": "bot-token"},
                None,
            ),
        ):
            with patch(
                "app.utils.notification.channels.external.aiohttp.ClientSession",
                side_effect=RuntimeError("connection refused"),
            ):
                status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.status == NotificationStatus.FAILED
        assert "connection refused" in (status.error_message or "")


# ========================================================================
# DiscordChannelAdapter specifics
# ========================================================================


@pytest.mark.unit
class TestDiscordAdapterProperties:
    """Tests for DiscordChannelAdapter-specific properties."""

    def test_channel_type(self) -> None:
        assert DiscordChannelAdapter().channel_type == CHANNEL_TYPE_DISCORD

    def test_platform_name(self) -> None:
        assert DiscordChannelAdapter().platform_name == CHANNEL_TYPE_DISCORD

    def test_bold_marker(self) -> None:
        assert DiscordChannelAdapter().bold_marker == "**"

    def test_max_message_length(self) -> None:
        assert DiscordChannelAdapter.MAX_MESSAGE_LENGTH == 2000

    def test_get_bot_token(self) -> None:
        adapter = DiscordChannelAdapter()
        with patch("app.utils.notification.channels.discord.settings") as s:
            s.DISCORD_BOT_TOKEN = "test-token"
            assert adapter._get_bot_token() == "test-token"

    def test_get_bot_token_none(self) -> None:
        adapter = DiscordChannelAdapter()
        with patch("app.utils.notification.channels.discord.settings") as s:
            s.DISCORD_BOT_TOKEN = None
            assert adapter._get_bot_token() is None

    def test_session_kwargs(self) -> None:
        adapter = DiscordChannelAdapter()
        ctx = {"token": "bot-tok", "platform_user_id": "123"}
        kwargs = adapter._session_kwargs(ctx)
        assert kwargs["headers"]["Authorization"] == "Bot bot-tok"
        assert kwargs["headers"]["Content-Type"] == "application/json"


@pytest.mark.unit
class TestDiscordSetupSender:
    """Tests for DiscordChannelAdapter._setup_sender."""

    async def test_successful_dm_channel_creation(self) -> None:
        """Returns a send function when DM channel is created successfully."""
        adapter = DiscordChannelAdapter()
        ctx = {"token": "bot-tok", "platform_user_id": "123"}

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id": "dm-channel-id"})
        mock_resp.text = AsyncMock(return_value="")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        send_fn, err = await adapter._setup_sender(mock_session, ctx)

        assert err is None
        assert send_fn is not None

    async def test_dm_channel_creation_failure(self) -> None:
        """Returns error status when DM channel API call fails."""
        adapter = DiscordChannelAdapter()
        ctx = {"token": "bot-tok", "platform_user_id": "123"}

        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.text = AsyncMock(return_value="Forbidden")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        send_fn, err = await adapter._setup_sender(mock_session, ctx)

        assert send_fn is None
        assert err is not None
        assert err.status == NotificationStatus.FAILED
        assert "403" in (err.error_message or "")

    async def test_dm_channel_missing_id(self) -> None:
        """Returns error when response is 200 but has no channel id."""
        adapter = DiscordChannelAdapter()
        ctx = {"token": "bot-tok", "platform_user_id": "123"}

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={})
        mock_resp.text = AsyncMock(return_value="")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        send_fn, err = await adapter._setup_sender(mock_session, ctx)

        assert send_fn is None
        assert err is not None
        assert "id missing" in (err.error_message or "").lower()


# ========================================================================
# TelegramChannelAdapter specifics
# ========================================================================


@pytest.mark.unit
class TestTelegramAdapterProperties:
    """Tests for TelegramChannelAdapter-specific properties."""

    def test_channel_type(self) -> None:
        assert TelegramChannelAdapter().channel_type == CHANNEL_TYPE_TELEGRAM

    def test_platform_name(self) -> None:
        assert TelegramChannelAdapter().platform_name == CHANNEL_TYPE_TELEGRAM

    def test_bold_marker(self) -> None:
        # Telegram adapter doesn't use bold_marker (overrides transform)
        assert TelegramChannelAdapter().bold_marker == ""

    def test_max_message_length(self) -> None:
        assert TelegramChannelAdapter.MAX_MESSAGE_LENGTH == 4096

    def test_get_bot_token(self) -> None:
        adapter = TelegramChannelAdapter()
        with patch("app.utils.notification.channels.telegram.settings") as s:
            s.TELEGRAM_BOT_TOKEN = "tg-token"
            assert adapter._get_bot_token() == "tg-token"

    def test_get_bot_token_none(self) -> None:
        adapter = TelegramChannelAdapter()
        with patch("app.utils.notification.channels.telegram.settings") as s:
            s.TELEGRAM_BOT_TOKEN = None
            assert adapter._get_bot_token() is None

    def test_session_kwargs_empty(self) -> None:
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}
        kwargs = adapter._session_kwargs(ctx)
        assert kwargs == {}


@pytest.mark.unit
class TestTelegramTransform:
    """Tests for TelegramChannelAdapter.transform."""

    async def test_standard_message(self) -> None:
        """Standard message returns plain text format."""
        adapter = TelegramChannelAdapter()
        request = _make_request(title="Title", body="Body text")

        content = await adapter.transform(request)

        assert content["text"] == "Title\nBody text"

    async def test_standard_message_no_title(self) -> None:
        """When title is empty, only body is returned."""
        adapter = TelegramChannelAdapter()
        request = _make_request(title="", body="Just body")

        content = await adapter.transform(request)

        assert content["text"] == "Just body"

    async def test_workflow_execution_content(self) -> None:
        """Workflow execution rich content returns workflow_messages format."""
        adapter = TelegramChannelAdapter()
        request = _make_request(
            title="WF Title",
            body="Duration: 10s",
            rich_content={
                "type": "workflow_execution",
                "messages": ["Step 1"],
                "conversation_id": "conv-1",
            },
        )

        with patch("app.utils.notification.channels.telegram.settings") as s:
            s.FRONTEND_URL = "https://app.test.com"
            content = await adapter.transform(request)

        assert content["type"] == "workflow_messages"
        assert "WF Title" in content["header"]
        assert content["messages"] == ["Step 1"]
        assert "conv-1" in content["footer"]


@pytest.mark.unit
class TestTelegramSetupSender:
    """Tests for TelegramChannelAdapter._setup_sender."""

    async def test_returns_send_function(self) -> None:
        """_setup_sender returns a callable send function."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}
        mock_session = AsyncMock()

        send_fn, err = await adapter._setup_sender(mock_session, ctx)

        assert err is None
        assert send_fn is not None
        assert callable(send_fn)


@pytest.mark.unit
class TestTelegramSendMessage:
    """Tests for TelegramChannelAdapter._send_message."""

    async def test_successful_send(self) -> None:
        """Returns None on 200 response."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}

        mock_resp = AsyncMock()
        mock_resp.status = 200

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        result = await adapter._send_message(mock_session, ctx, "Hello", [])

        assert result is None

    async def test_send_with_entities(self) -> None:
        """Entities are included in payload when provided."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}
        entities = [{"type": "bold", "offset": 0, "length": 5}]

        mock_resp = AsyncMock()
        mock_resp.status = 200

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        result = await adapter._send_message(mock_session, ctx, "Hello", entities)

        assert result is None
        # Verify entities were in the payload
        post_call = mock_session.post.call_args
        payload = (
            post_call[1].get("json") or post_call[0][1]
            if len(post_call[0]) > 1
            else post_call[1]["json"]
        )
        assert "entities" in payload

    async def test_send_failure(self) -> None:
        """Returns error text on non-200 response."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}

        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad Request: chat not found")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        result = await adapter._send_message(mock_session, ctx, "Hello", [])

        assert result == "Bad Request: chat not found"

    async def test_send_empty_entities_not_in_payload(self) -> None:
        """Empty entities list is not included in the payload."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}

        mock_resp = AsyncMock()
        mock_resp.status = 200

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = cm

        await adapter._send_message(mock_session, ctx, "Hello", [])

        post_call = mock_session.post.call_args
        payload = post_call[1].get("json", {})
        assert "entities" not in payload


@pytest.mark.unit
class TestTelegramDeliver:
    """Tests for TelegramChannelAdapter.deliver (full flow)."""

    async def test_deliver_not_linked(self) -> None:
        """Returns skipped when user has no Telegram link."""
        adapter = TelegramChannelAdapter()

        with patch(
            "app.utils.notification.channels.external.PlatformLinkService"
        ) as svc:
            svc.get_linked_platforms = AsyncMock(return_value={})
            status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.skipped is True

    async def test_deliver_standard_message_success(self) -> None:
        """Successful standard message delivery."""
        adapter = TelegramChannelAdapter()

        with (
            patch.object(
                adapter,
                "_get_platform_context",
                new_callable=AsyncMock,
                return_value=(
                    {"platform_user_id": "456", "token": "tg-tok"},
                    None,
                ),
            ),
            patch.object(
                adapter,
                "_send_markdown",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.utils.notification.channels.telegram.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            status = await adapter.deliver({"text": "hello world"}, "user-1")

        assert status.status == NotificationStatus.DELIVERED

    async def test_deliver_standard_message_error(self) -> None:
        """Error during standard message delivery returns FAILED."""
        adapter = TelegramChannelAdapter()

        with (
            patch.object(
                adapter,
                "_get_platform_context",
                new_callable=AsyncMock,
                return_value=(
                    {"platform_user_id": "456", "token": "tg-tok"},
                    None,
                ),
            ),
            patch.object(
                adapter,
                "_send_markdown",
                new_callable=AsyncMock,
                return_value="send failed",
            ),
            patch(
                "app.utils.notification.channels.telegram.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.status == NotificationStatus.FAILED

    async def test_deliver_workflow_messages(self) -> None:
        """Workflow messages flow: header + messages + footer."""
        adapter = TelegramChannelAdapter()

        with (
            patch.object(
                adapter,
                "_get_platform_context",
                new_callable=AsyncMock,
                return_value=(
                    {"platform_user_id": "456", "token": "tg-tok"},
                    None,
                ),
            ),
            patch(
                "app.utils.notification.channels.telegram.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            # Patch _send_message used by send_plain and _send_markdown
            with patch.object(
                adapter,
                "_send_message",
                new_callable=AsyncMock,
                return_value=None,
            ):
                # Also patch _send_markdown
                with patch.object(
                    adapter,
                    "_send_markdown",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    content = {
                        "type": "workflow_messages",
                        "header": "WF header",
                        "messages": ["msg1", "msg2"],
                        "footer": "WF footer",
                    }
                    status = await adapter.deliver(content, "user-1")

        assert status.status == NotificationStatus.DELIVERED

    async def test_deliver_workflow_header_error(self) -> None:
        """Error sending workflow header returns FAILED."""
        adapter = TelegramChannelAdapter()

        with (
            patch.object(
                adapter,
                "_get_platform_context",
                new_callable=AsyncMock,
                return_value=(
                    {"platform_user_id": "456", "token": "tg-tok"},
                    None,
                ),
            ),
            patch(
                "app.utils.notification.channels.telegram.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            # send_plain (via _send_message) fails for header
            with patch.object(
                adapter,
                "_send_message",
                new_callable=AsyncMock,
                return_value="header error",
            ):
                content = {
                    "type": "workflow_messages",
                    "header": "WF header",
                    "messages": [],
                    "footer": "",
                }
                status = await adapter.deliver(content, "user-1")

        assert status.status == NotificationStatus.FAILED
        assert "header" in (status.error_message or "").lower()

    async def test_deliver_exception_returns_error(self) -> None:
        """Unexpected exception during deliver returns error status."""
        adapter = TelegramChannelAdapter()

        with patch.object(
            adapter,
            "_get_platform_context",
            new_callable=AsyncMock,
            return_value=(
                {"platform_user_id": "456", "token": "tg-tok"},
                None,
            ),
        ):
            with patch(
                "app.utils.notification.channels.telegram.aiohttp.ClientSession",
                side_effect=RuntimeError("network failure"),
            ):
                status = await adapter.deliver({"text": "hello"}, "user-1")

        assert status.status == NotificationStatus.FAILED
        assert "network failure" in (status.error_message or "")


# ========================================================================
# TelegramChannelAdapter markdown helpers
# ========================================================================


@pytest.mark.unit
class TestTelegramMarkdownHelpers:
    """Tests for Telegram markdown conversion static methods."""

    def test_md_to_entities_plain_text(self) -> None:
        """Plain text returns the same text with empty entities."""
        plain, entities = TelegramChannelAdapter._md_to_entities("hello world")
        assert "hello" in plain
        # No markdown → no (or trivial) entities
        assert isinstance(entities, list)

    def test_chunks_from_md_short_text(self) -> None:
        """Short text returns a single chunk."""
        chunks = TelegramChannelAdapter._chunks_from_md("short", max_len=4096)
        assert len(chunks) >= 1
        assert isinstance(chunks[0], tuple)
        assert len(chunks[0]) == 2  # (text, entities)

    def test_chunks_from_md_returns_list_of_tuples(self) -> None:
        """Each chunk is a (str, list) tuple."""
        chunks = TelegramChannelAdapter._chunks_from_md("test text", max_len=100)
        for chunk_text, chunk_entities in chunks:
            assert isinstance(chunk_text, str)
            assert isinstance(chunk_entities, list)


@pytest.mark.unit
class TestTelegramSendMarkdown:
    """Tests for TelegramChannelAdapter._send_markdown."""

    async def test_send_markdown_success(self) -> None:
        """Converts markdown and sends chunked messages."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}
        mock_session = AsyncMock()

        with patch.object(
            adapter,
            "_chunks_from_md",
            return_value=[("plain text", [])],
        ):
            with patch.object(
                adapter,
                "_send_message",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_send:
                result = await adapter._send_markdown(mock_session, ctx, "**bold**")

        assert result is None
        mock_send.assert_awaited_once()

    async def test_send_markdown_chunk_error(self) -> None:
        """Returns error from first failing chunk."""
        adapter = TelegramChannelAdapter()
        ctx = {"token": "tg-tok", "platform_user_id": "456"}
        mock_session = AsyncMock()

        with patch.object(
            adapter,
            "_chunks_from_md",
            return_value=[("chunk1", []), ("chunk2", [])],
        ):
            with patch.object(
                adapter,
                "_send_message",
                new_callable=AsyncMock,
                side_effect=[None, "chunk 2 failed"],
            ):
                result = await adapter._send_markdown(mock_session, ctx, "long text")

        assert result == "chunk 2 failed"
