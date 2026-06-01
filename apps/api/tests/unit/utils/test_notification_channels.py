"""Unit tests for notification channel adapters (inapp, base helpers, external).

External delivery now publishes a CommonMark envelope to the platform's
outbound queue; all platform formatting and sending live in the bots, so these
tests cover the transform-to-parts and publish behaviour only.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.notifications import (
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_WHATSAPP,
)
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
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
from app.utils.notification.channels.slack import SlackChannelAdapter
from app.utils.notification.channels.telegram import TelegramChannelAdapter
from app.utils.notification.channels.whatsapp import WhatsAppChannelAdapter

_SENTINEL = object()


def _make_request(
    channels: Any = _SENTINEL,
    title: str = "Test Title",
    body: str = "Test body text",
    actions: list[NotificationAction] | None = None,
    rich_content: dict[str, Any] | None = None,
) -> NotificationRequest:
    resolved_channels: list[ChannelConfig]
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


def _make_redirect_action(label: str = "View", url: str = "/test") -> NotificationAction:
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
    def test_success_helper(self) -> None:
        status = InAppChannelAdapter()._success()
        assert status.channel_type == CHANNEL_TYPE_INAPP
        assert status.status == NotificationStatus.DELIVERED
        assert status.delivered_at is not None

    def test_error_helper(self) -> None:
        status = InAppChannelAdapter()._error("something broke")
        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "something broke"
        assert status.skipped is False

    def test_skipped_helper(self) -> None:
        status = InAppChannelAdapter()._skipped("not linked")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True
        assert status.error_message == "not linked"


# ========================================================================
# InAppChannelAdapter
# ========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
class TestInAppChannelAdapter:
    def test_channel_type(self) -> None:
        assert InAppChannelAdapter().channel_type == CHANNEL_TYPE_INAPP

    def test_can_handle_with_inapp_channel(self) -> None:
        request = _make_request(channels=[ChannelConfig(channel_type="inapp", enabled=True)])
        assert InAppChannelAdapter().can_handle(request) is True

    def test_can_handle_without_inapp_channel(self) -> None:
        request = _make_request(channels=[ChannelConfig(channel_type="telegram", enabled=True)])
        assert InAppChannelAdapter().can_handle(request) is False

    async def test_transform_basic(self) -> None:
        request = _make_request(title="Hello", body="World")
        content = await InAppChannelAdapter().transform(request)
        assert content["title"] == "Hello"
        assert content["body"] == "World"
        assert content["metadata"] == {"key": "value"}

    async def test_successful_delivery(self) -> None:
        content = {"id": "notif-1", "title": "Test"}
        with patch("app.utils.notification.channels.inapp.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            status = await InAppChannelAdapter().deliver(content, "user-1")
        assert status.status == NotificationStatus.DELIVERED
        ws.broadcast_to_user.assert_awaited_once()

    async def test_delivery_failure(self) -> None:
        with patch("app.utils.notification.channels.inapp.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("ws down"))
            status = await InAppChannelAdapter().deliver({"id": "n"}, "user-1")
        assert status.status == NotificationStatus.FAILED
        assert "ws down" in (status.error_message or "")


# ========================================================================
# ExternalPlatformAdapter.transform (via the Discord adapter)
# ========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
class TestExternalPlatformTransform:
    async def test_standard_message_parts(self) -> None:
        request = _make_request(title="My Title", body="My body")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**My Title**\nMy body"]

    async def test_standard_message_without_title(self) -> None:
        request = _make_request(title="", body="just body")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["just body"]

    async def test_redirect_actions_appended_as_commonmark_link(self) -> None:
        action = _make_redirect_action(label="View Task", url="/todos/1")
        request = _make_request(title="Task", body="details", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert "[View Task](https://app.example.com/todos/1)" in content["parts"][0]

    async def test_workflow_execution_parts(self) -> None:
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
            content = await DiscordChannelAdapter().transform(request)
        parts = content["parts"]
        assert "**Workflow Done**" in parts[0]
        assert "Step 1 result" in parts
        assert "Step 2 result" in parts
        assert any("conv-123" in p for p in parts)  # footer link is its own part

    async def test_workflow_no_conversation_id_drops_footer(self) -> None:
        request = _make_request(
            title="WF",
            body="Done",
            rich_content={"type": "workflow_execution", "messages": [], "conversation_id": ""},
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert all("View full results" not in p for p in content["parts"])


# ========================================================================
# ExternalPlatformAdapter.deliver (publishes to the outbound queue)
# ========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
class TestExternalPlatformDeliver:
    async def test_deliver_publishes_and_maps_success(self) -> None:
        with patch(
            "app.utils.notification.channels.external.publish_outbound_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as pub:
            status = await DiscordChannelAdapter().deliver({"parts": ["hello"]}, "user-1")
        pub.assert_awaited_once_with(ConversationSource.DISCORD, "user-1", ["hello"])
        assert status.status == NotificationStatus.DELIVERED
        assert status.skipped is False

    async def test_deliver_maps_failure_to_skipped(self) -> None:
        with patch(
            "app.utils.notification.channels.external.publish_outbound_message",
            new_callable=AsyncMock,
            return_value=False,
        ):
            status = await DiscordChannelAdapter().deliver({"parts": ["hello"]}, "user-1")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True


@pytest.mark.unit
class TestExternalAdapterIdentity:
    @pytest.mark.parametrize(
        "adapter_cls, channel_type, platform",
        [
            (WhatsAppChannelAdapter, CHANNEL_TYPE_WHATSAPP, ConversationSource.WHATSAPP),
            (SlackChannelAdapter, CHANNEL_TYPE_SLACK, ConversationSource.SLACK),
            (TelegramChannelAdapter, CHANNEL_TYPE_TELEGRAM, ConversationSource.TELEGRAM),
            (DiscordChannelAdapter, CHANNEL_TYPE_DISCORD, ConversationSource.DISCORD),
        ],
    )
    def test_channel_type_and_platform(self, adapter_cls, channel_type, platform) -> None:
        adapter = adapter_cls()
        assert adapter.channel_type == channel_type
        assert adapter.platform is platform

    def test_can_handle_always_true(self) -> None:
        assert DiscordChannelAdapter().can_handle(_make_request(channels=[])) is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestExternalTransformBrutalEdges:
    """Pin the exact CommonMark output: no stray leading/trailing whitespace,
    and no platform-specific markdown leaking back into the Python side."""

    async def test_title_only_has_no_trailing_newline(self) -> None:
        # A reminder with a title and empty body must not emit a dangling "\n".
        request = _make_request(title="Reminder", body="")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**Reminder**"]

    async def test_actions_only_has_no_leading_newline(self) -> None:
        # With empty title/body, an action link must not be prefixed by "\n\n".
        action = _make_redirect_action(label="Open", url="/x")
        request = _make_request(title="", body="", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["[Open](https://app.example.com/x)"]

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            WhatsAppChannelAdapter,
            SlackChannelAdapter,
            TelegramChannelAdapter,
            DiscordChannelAdapter,
        ],
    )
    async def test_transform_emits_commonmark_for_every_platform(self, adapter_cls) -> None:
        # The refactor's core promise: Python emits platform-AGNOSTIC CommonMark.
        # If convert_to_whatsapp_markdown (etc.) is re-added here, WhatsApp's
        # title becomes *Reminder* — this catches that regression on all four.
        request = _make_request(title="Reminder", body="Take a break")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter_cls().transform(request)
        assert content["parts"] == ["**Reminder**\nTake a break"]

    async def test_workflow_filters_blank_messages(self) -> None:
        request = _make_request(
            title="WF",
            body="done",
            rich_content={
                "type": "workflow_execution",
                "messages": ["real", "", "   ", "also real"],
                "conversation_id": "c1",
            },
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == [
            "**WF**\ndone",
            "real",
            "also real",
            "[View full results](https://app.example.com/c/c1)",
        ]

    async def test_redirect_action_with_no_url_is_skipped_not_crashed(self) -> None:
        # A REDIRECT action whose config.redirect is None must be skipped, not
        # dereferenced (config.redirect.url would raise).
        action = NotificationAction(
            type=ActionType.REDIRECT,
            label="X",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(),
        )
        request = _make_request(title="T", body="B", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**T**\nB"]
