"""Channel adapter unit tests: the base status helpers, the CommonMark a chat app is sent and how a post maps to a status.

Delivery itself (publish, DM session, Notice) is proven against real Mongo in
tests/integration/real/test_notify_pipeline_real.py.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.notifications import (
    CHANNEL_TYPE_CONVERSATION,
    NotificationChannel,
    NotificationKind,
    ProactiveMessageClass,
)
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.models.notification.details_models import TodoNotification
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
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.utils.errors import ConversationNotFoundError
from app.utils.notification.channels.conversation import (
    ConversationChannelAdapter,
    ConversationPayload,
)
from app.utils.notification.channels.discord import DiscordChannelAdapter
from app.utils.notification.channels.external import ExternalPayload, notice_origin
from app.utils.notification.channels.imessage import ImessageChannelAdapter
from app.utils.notification.channels.slack import SlackChannelAdapter
from app.utils.notification.channels.telegram import TelegramChannelAdapter
from app.utils.notification.channels.whatsapp import WhatsAppChannelAdapter

_SENTINEL = object()
_DETAILS = TodoNotification(kind=NotificationKind.TODO, todo_id="todo-1")


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
        details=_DETAILS,
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
        status = TelegramChannelAdapter()._success()
        assert status.channel_type == NotificationChannel.TELEGRAM
        assert status.status == NotificationStatus.DELIVERED
        assert status.delivered_at is not None

    def test_error_helper(self) -> None:
        status = TelegramChannelAdapter()._error("something broke")
        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "something broke"
        assert status.skipped is False

    def test_skipped_helper(self) -> None:
        status = TelegramChannelAdapter()._skipped("not linked")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True
        assert status.error_message == "not linked"


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
        assert content.text == "**My Title**\nMy body"
        assert content.origin == notice_origin(request)
        assert content.message_class is request.message_class

    async def test_standard_message_without_title(self) -> None:
        request = _make_request(title="", body="just body")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content.text == "just body"

    async def test_redirect_actions_appended_as_commonmark_link(self) -> None:
        action = _make_redirect_action(label="View Task", url="/todos/1")
        request = _make_request(title="Task", body="details", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert "[View Task](https://app.example.com/todos/1)" in content.text

    async def test_the_whole_payload_carries_every_link_on_one_line_after_the_text(
        self,
    ) -> None:
        actions = [
            _make_redirect_action(label="View Task", url="/todos/1"),
            _make_redirect_action(label="Open", url="/x"),
        ]
        request = _make_request(title="Task", body="details", actions=actions)
        with patch("app.utils.notification.channels.external.settings") as s:
            # A path prefix ending in "X" too: only the trailing slash is trimmed.
            s.FRONTEND_URL = "https://example.com/INBOX/"
            content = await DiscordChannelAdapter().transform(request)
        assert content == ExternalPayload(
            notification_id="notif-1",
            text=(
                "**Task**\ndetails\n\n"
                "[View Task](https://example.com/INBOX/todos/1) · [Open](https://example.com/INBOX/x)"
            ),
            origin=notice_origin(request),
            message_class=ProactiveMessageClass.ROUTINE,
        )

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
        assert content.text == "**Workflow Done**\nCompleted in 30s"


LINKED_USER = UserDocument(id="user-1", platform_links={"discord": {"id": "dc-7"}})
EXTERNAL = "app.utils.notification.channels.external"


def _payload(text: str) -> ExternalPayload:
    return ExternalPayload(
        notification_id="notif-1",
        text=text,
        origin="notification from ai_agent",
        message_class=ProactiveMessageClass.ROUTINE,
    )


@pytest.mark.asyncio
class TestExternalPlatformDeliver:
    async def test_deliver_posts_into_the_linked_dm_and_maps_success(self) -> None:
        with (
            patch(f"{EXTERNAL}.user_repository.get", AsyncMock(return_value=LINKED_USER)),
            patch(
                f"{EXTERNAL}.post_to_platform_chat",
                new_callable=AsyncMock,
                return_value=OutboundResult.PUBLISHED,
            ) as post,
        ):
            status = await DiscordChannelAdapter().deliver(_payload("hello"), "user-1")

        kwargs = post.await_args.kwargs
        assert kwargs["user"].user_id == "user-1"
        assert kwargs["channel"] == ChatChannel(
            source=ConversationSource.DISCORD, platform_user_id="dc-7", basis="priority"
        )
        assert (kwargs["message"].text, kwargs["message"].origin) == (
            "hello",
            "notification from ai_agent",
        )
        assert kwargs["message"].message_class is ProactiveMessageClass.ROUTINE
        # Keyed by the notification, so a retried notification posts its Notice once.
        assert kwargs["message"].notice_id == "notice:notif-1"
        assert status.status == NotificationStatus.DELIVERED
        assert status.skipped is False

    async def test_an_unlinked_platform_is_skipped_without_posting(self) -> None:
        with (
            patch(
                f"{EXTERNAL}.user_repository.get",
                AsyncMock(return_value=UserDocument(id="user-1")),
            ) as get,
            patch(f"{EXTERNAL}.post_to_platform_chat", new_callable=AsyncMock) as post,
        ):
            status = await DiscordChannelAdapter().deliver(_payload("hello"), "user-1")

        get.assert_awaited_once_with("user-1")
        post.assert_not_awaited()
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True
        assert status.error_message == "discord: not linked"

    async def test_blank_text_is_skipped_without_a_lookup(self) -> None:
        with patch(f"{EXTERNAL}.user_repository.get", new_callable=AsyncMock) as get:
            status = await DiscordChannelAdapter().deliver(_payload("  "), "user-1")

        get.assert_not_awaited()
        assert status.skipped is True
        assert status.error_message == "discord: nothing to send"

    async def test_a_message_held_for_quiet_hours_is_pending_not_failed(self) -> None:
        with (
            patch(f"{EXTERNAL}.user_repository.get", AsyncMock(return_value=LINKED_USER)),
            patch(
                f"{EXTERNAL}.post_to_platform_chat",
                new_callable=AsyncMock,
                return_value=OutboundResult.DEFERRED,
            ),
        ):
            status = await DiscordChannelAdapter().deliver(_payload("hello"), "user-1")

        assert status.status == NotificationStatus.PENDING
        assert status.skipped is False
        assert status.error_message is None

    async def test_deliver_maps_skipped_to_skipped(self) -> None:
        with (
            patch(f"{EXTERNAL}.user_repository.get", AsyncMock(return_value=LINKED_USER)),
            patch(
                f"{EXTERNAL}.post_to_platform_chat",
                new_callable=AsyncMock,
                return_value=OutboundResult.SKIPPED,
            ),
        ):
            status = await DiscordChannelAdapter().deliver(_payload("hello"), "user-1")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is True

    async def test_deliver_maps_failed_to_error_not_skipped(self) -> None:
        # A post that failed is a real failure, NOT a skip, so retries and
        # alerting that key off non-skipped FAILED still fire in an outage.
        with (
            patch(f"{EXTERNAL}.user_repository.get", AsyncMock(return_value=LINKED_USER)),
            patch(
                f"{EXTERNAL}.post_to_platform_chat",
                new_callable=AsyncMock,
                return_value=OutboundResult.FAILED,
            ),
        ):
            status = await DiscordChannelAdapter().deliver(_payload("hello"), "user-1")
        assert status.status == NotificationStatus.FAILED
        assert status.skipped is False


class TestExternalAdapterIdentity:
    @pytest.mark.parametrize(
        "adapter_cls, channel_type, platform",
        [
            (WhatsAppChannelAdapter, NotificationChannel.WHATSAPP, ConversationSource.WHATSAPP),
            (SlackChannelAdapter, NotificationChannel.SLACK, ConversationSource.SLACK),
            (TelegramChannelAdapter, NotificationChannel.TELEGRAM, ConversationSource.TELEGRAM),
            (DiscordChannelAdapter, NotificationChannel.DISCORD, ConversationSource.DISCORD),
            (ImessageChannelAdapter, NotificationChannel.IMESSAGE, ConversationSource.IMESSAGE),
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
    """Pins the exact CommonMark output: no stray whitespace, no platform-specific markdown leaking through."""

    async def test_title_only_has_no_trailing_newline(self) -> None:
        # A reminder with a title and empty body must not emit a dangling "\n".
        request = _make_request(title="Reminder", body="")
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content.text == "**Reminder**"

    async def test_actions_only_has_no_leading_newline(self) -> None:
        # With empty title/body, an action link must not be prefixed by "\n\n".
        action = _make_redirect_action(label="Open", url="/x")
        request = _make_request(title="", body="", actions=[action])
        with patch("app.utils.notification.channels.external.settings") as s:
            s.FRONTEND_URL = "https://app.example.com"
            content = await DiscordChannelAdapter().transform(request)
        assert content.text == "[Open](https://app.example.com/x)"

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
        assert content.text == "**Reminder**\nTake a break"

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
        assert content.text == "**T**\nB"


_CONVERSATION = "app.utils.notification.channels.conversation"


class TestConversationChannel:
    def test_it_handles_only_a_notification_that_names_a_conversation(self) -> None:
        adapter = ConversationChannelAdapter()
        request = _make_request()

        assert adapter.channel_type == CHANNEL_TYPE_CONVERSATION
        assert adapter.can_handle(request) is False
        assert adapter.can_handle(request.model_copy(update={"conversation_id": "c1"})) is True

    async def test_transform_carries_the_conversation_the_text_and_the_origin(self) -> None:
        request = _make_request(title="Standup").model_copy(
            update={"conversation_id": "c1", "message": "standup moved to 10"}
        )

        payload = await ConversationChannelAdapter().transform(request)

        assert payload == ConversationPayload(
            conversation_id="c1",
            notification_id="notif-1",
            text="standup moved to 10",
            origin=f'{NotificationSourceEnum.AI_TODO_ADDED.value} "Standup" (id notif-1)',
        )

    async def test_transform_refuses_a_notification_without_a_conversation(self) -> None:
        with pytest.raises(ValueError) as refused:
            await ConversationChannelAdapter().transform(_make_request())
        assert (
            str(refused.value) == "a conversation notice needs the notification's conversation_id"
        )

    async def test_deliver_logs_the_notice_once_under_the_notification_id(self) -> None:
        payload = ConversationPayload("c1", "notif-1", "hi", "origin")
        ports = object()
        with (
            patch(f"{_CONVERSATION}.runtime_ports", return_value=ports),
            patch(f"{_CONVERSATION}.accept", new=AsyncMock()) as accept,
        ):
            result = await ConversationChannelAdapter().deliver(payload, "user-1")

        accept.assert_awaited_once_with(
            ports, "c1", "user-1", Notice(id="notice:notif-1", text="hi", origin="origin")
        )
        assert (result.channel_type, result.status, result.error_message) == (
            CHANNEL_TYPE_CONVERSATION,
            NotificationStatus.DELIVERED,
            None,
        )

    @pytest.mark.parametrize(
        ("text", "refusal", "error"),
        [
            ("  ", None, "conversation: nothing to say"),
            (
                "hi",
                ConversationNotFoundError(message="conversation c1 not found"),
                "conversation: deleted",
            ),
        ],
    )
    async def test_deliver_skips_an_empty_notice_and_a_deleted_conversation(
        self, text: str, refusal: Exception | None, error: str
    ) -> None:
        payload = ConversationPayload("c1", "notif-1", text, "origin")
        with (
            patch(f"{_CONVERSATION}.runtime_ports"),
            patch(f"{_CONVERSATION}.accept", new=AsyncMock(side_effect=refusal)),
        ):
            result = await ConversationChannelAdapter().deliver(payload, "user-1")

        assert (result.status, result.skipped, result.error_message) == (
            NotificationStatus.FAILED,
            True,
            error,
        )
