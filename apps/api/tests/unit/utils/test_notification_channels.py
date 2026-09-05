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
    CHANNEL_TYPE_IMESSAGE,
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
from app.services.outbound_delivery import OutboundResult
from app.utils.notification.channels.discord import DiscordChannelAdapter
from app.utils.notification.channels.imessage import ImessageChannelAdapter
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
    metadata: dict[str, Any] | None = None,
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
        metadata={"key": "value"} if metadata is None else metadata,
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


@pytest.mark.asyncio
class TestInAppChannelAdapter:
    def test_channel_type(self) -> None:
        assert InAppChannelAdapter().channel_type == CHANNEL_TYPE_INAPP

    def test_can_handle_with_inapp_channel(self) -> None:
        request = _make_request(channels=[ChannelConfig(channel_type="inapp", enabled=True)])
        assert InAppChannelAdapter().can_handle(request) is True

    def test_can_handle_without_inapp_channel(self) -> None:
        # InAppChannelAdapter always returns True — in-app delivery is unconditional.
        # The orchestrator handles targeting; checking the channel list here would
        # silently skip real-time pushes when channels are auto-injected (empty list).
        request = _make_request(channels=[ChannelConfig(channel_type="telegram", enabled=True)])
        assert InAppChannelAdapter().can_handle(request) is True

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
        # Pins the whole string, not a substring: the blank line between body and
        # links ("\n\n", not the "\n" default) and the " · " between two links are
        # the parts a mutation can silently change while a substring check passes.
        request = _make_request(
            title="Task",
            body="details",
            actions=[
                _make_redirect_action(label="View Task", url="/todos/1"),
                _make_redirect_action(label="Snooze", url="/todos/1/snooze"),
            ],
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == [
            "**Task**\ndetails\n\n"
            "[View Task](https://app.example.com/todos/1)"
            " · "
            "[Snooze](https://app.example.com/todos/1/snooze)"
        ]

    async def test_non_redirect_actions_add_no_link_block(self) -> None:
        # An action list that yields no links must leave the text untouched — no
        # trailing separator, no empty link block.
        action = NotificationAction(
            type=ActionType.API_CALL,
            label="Approve",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(),
        )
        request = _make_request(title="Task", body="details", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**Task**\ndetails"]

    async def test_frontend_url_trailing_slash_is_not_doubled(self) -> None:
        request = _make_request(
            title="Task",
            body="details",
            actions=[_make_redirect_action(label="View", url="/todos/1")],
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com/"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**Task**\ndetails\n\n[View](https://app.example.com/todos/1)"]

    async def test_rich_content_is_ignored(self) -> None:
        # Workflow results now reach the user as real chat messages, not through
        # the notification. The external transform renders only title/body and
        # ignores rich_content entirely (no result bubbles, no "view results").
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
        assert content["parts"] == ["**Workflow Done**\nCompleted in 30s"]


@pytest.mark.asyncio
class TestExternalTransformPlatformParts:
    """``metadata.platform_parts`` is the sender-rendered chat voice.

    When present it replaces the title/body rendering entirely, in order, one
    part per message bubble.
    """

    async def test_platform_parts_replace_title_body_rendering(self) -> None:
        request = _make_request(
            title="Your morning brief",
            body="3 things need you",
            actions=[_make_redirect_action(label="Open", url="/briefing")],
            metadata={"platform_parts": ["morning!", "3 things need you today"]},
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        # Exact list, in order: neither the title/body text nor the action link
        # may leak in, and the bubbles must not be reordered or merged.
        assert content["parts"] == ["morning!", "3 things need you today"]

    async def test_platform_parts_are_stringified_and_emptied_out(self) -> None:
        # Non-string parts are coerced (a sender may stage a number), and empty
        # parts are dropped so no blank bubble is ever sent.
        request = _make_request(
            title="T",
            body="B",
            metadata={"platform_parts": ["first", "", 42, None, "last"]},
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["first", "42", "last"]

    async def test_all_empty_platform_parts_fall_back_to_title_body(self) -> None:
        request = _make_request(title="T", body="B", metadata={"platform_parts": ["", None]})
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**T**\nB"]

    @pytest.mark.parametrize("metadata", [{}, {"key": "value"}, {"platform_parts": None}])
    async def test_missing_platform_parts_falls_back_to_title_body(
        self, metadata: dict[str, Any]
    ) -> None:
        request = _make_request(title="T", body="B", metadata=metadata)
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content["parts"] == ["**T**\nB"]

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            WhatsAppChannelAdapter,
            SlackChannelAdapter,
            TelegramChannelAdapter,
            DiscordChannelAdapter,
            ImessageChannelAdapter,
        ],
    )
    async def test_platform_parts_pass_through_unformatted_on_every_platform(
        self, adapter_cls: type
    ) -> None:
        request = _make_request(
            title="T", body="B", metadata={"platform_parts": ["hey", "here's the thing"]}
        )
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter_cls().transform(request)
        assert content["parts"] == ["hey", "here's the thing"]


# ========================================================================
# ExternalPlatformAdapter.deliver (publishes to the outbound queue)
# ========================================================================


@pytest.mark.asyncio
class TestExternalPlatformDeliver:
    async def test_deliver_publishes_and_maps_success(self) -> None:
        with patch(
            "app.utils.notification.channels.external.publish_outbound_message",
            new_callable=AsyncMock,
            return_value=OutboundResult.PUBLISHED,
        ) as pub:
            status = await DiscordChannelAdapter().deliver({"parts": ["hello"]}, "user-1")
        pub.assert_awaited_once_with(ConversationSource.DISCORD, "user-1", ["hello"])
        assert status.status == NotificationStatus.DELIVERED
        assert status.skipped is False

    async def test_deliver_maps_skipped_to_skipped(self) -> None:
        # Unsupported platform / unlinked account / nothing to send: a genuine
        # skip, flagged so it isn't treated as a failure.
        with patch(
            "app.utils.notification.channels.external.publish_outbound_message",
            new_callable=AsyncMock,
            return_value=OutboundResult.SKIPPED,
        ):
            status = await DiscordChannelAdapter().deliver({"parts": ["hello"]}, "user-1")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True

    async def test_deliver_maps_failed_to_error_not_skipped(self) -> None:
        # Broker down / publish error: a real failure, NOT a skip — so retries
        # and alerting that key off non-skipped FAILED still fire in an outage.
        with patch(
            "app.utils.notification.channels.external.publish_outbound_message",
            new_callable=AsyncMock,
            return_value=OutboundResult.FAILED,
        ):
            status = await DiscordChannelAdapter().deliver({"parts": ["hello"]}, "user-1")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is False


class TestExternalAdapterIdentity:
    @pytest.mark.parametrize(
        "adapter_cls, channel_type, platform",
        [
            (WhatsAppChannelAdapter, CHANNEL_TYPE_WHATSAPP, ConversationSource.WHATSAPP),
            (SlackChannelAdapter, CHANNEL_TYPE_SLACK, ConversationSource.SLACK),
            (TelegramChannelAdapter, CHANNEL_TYPE_TELEGRAM, ConversationSource.TELEGRAM),
            (DiscordChannelAdapter, CHANNEL_TYPE_DISCORD, ConversationSource.DISCORD),
            (ImessageChannelAdapter, CHANNEL_TYPE_IMESSAGE, ConversationSource.IMESSAGE),
        ],
    )
    def test_channel_type_and_platform(self, adapter_cls, channel_type, platform) -> None:
        adapter = adapter_cls()
        assert adapter.channel_type == channel_type
        assert adapter.platform is platform

    def test_can_handle_always_true(self) -> None:
        assert DiscordChannelAdapter().can_handle(_make_request(channels=[])) is True


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
            ImessageChannelAdapter,
        ],
    )
    async def test_transform_emits_commonmark_for_every_platform(self, adapter_cls) -> None:
        # The refactor's core promise: Python emits platform-AGNOSTIC CommonMark.
        # If convert_to_whatsapp_markdown (etc.) is re-added here, WhatsApp's
        # title becomes *Reminder* — this catches that regression on all five.
        request = _make_request(title="Reminder", body="Take a break")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await adapter_cls().transform(request)
        assert content["parts"] == ["**Reminder**\nTake a break"]

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
