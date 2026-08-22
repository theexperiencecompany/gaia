"""Behavior tests for app.agents.core.background.workflow_platform_delivery.

Locks: delivery only happens for linked, enabled bot platforms carrying a
platform user id; the notification text is split into bubbles on the break
sentinel; each platform gets a persisted bot message and one outbound publish;
and every failure path stays best-effort (logs, never raises, never blocks
sibling platforms).
"""

from unittest.mock import AsyncMock, patch

from app.agents.core.background.workflow_platform_delivery import (
    _preferred_bot_platforms,
    deliver_workflow_result_to_platforms,
)
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.chat_models import ConversationSource
from app.services.outbound_delivery import OutboundResult

MODULE = "app.agents.core.background.workflow_platform_delivery"

USER: dict = {"user_id": "user-1", "email": "u@gaia.local"}
USER_ID = "user-1"
TEXT = f"Report is ready.{NEW_MESSAGE_BREAKER}It has 3 pages."

LINKED = {
    "telegram": {"platformUserId": "tg-123"},
    "slack": {"platformUserId": "sl-456"},
    "web": {"platformUserId": "web-1"},  # not a bot source -> excluded
    "whatsapp": {"platformUserId": ""},  # no platform id -> excluded
}

PREFERENCES: dict[str, bool] = {"telegram": True, "slack": True}


class TestPreferredBotPlatforms:
    async def test_keeps_linked_enabled_bot_platforms_only(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
        ):
            targets = await _preferred_bot_platforms(USER_ID)

        assert targets == [
            (ConversationSource.TELEGRAM, "tg-123"),
            (ConversationSource.SLACK, "sl-456"),
        ]

    async def test_disabled_preference_excludes_a_platform(self) -> None:
        prefs = {"telegram": True, "slack": False}
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=prefs)),
        ):
            targets = await _preferred_bot_platforms(USER_ID)

        assert targets == [(ConversationSource.TELEGRAM, "tg-123")]

    async def test_missing_preference_defaults_to_enabled(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
        ):
            targets = await _preferred_bot_platforms(USER_ID)

        assert len(targets) == 2

    async def test_lookup_failure_returns_no_targets(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms",
                AsyncMock(side_effect=RuntimeError("db down")),
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock()),
        ):
            assert await _preferred_bot_platforms(USER_ID) == []


class TestDeliverWorkflowResultToPlatforms:
    async def test_blank_text_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock()) as linked,
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock()),
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text="   "
            )

        linked.assert_not_called()

    async def test_no_targets_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value={})),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock()) as session,
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT
            )

        session.assert_not_called()

    async def test_happy_path_persists_and_publishes_to_each_target(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(
                f"{MODULE}.BotService.get_or_create_session",
                AsyncMock(side_effect=["tg-conv", "sl-conv"]),
            ) as session,
            patch(f"{MODULE}.update_messages", AsyncMock()) as update,
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as publish,
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT
            )

        assert session.await_count == 2
        assert update.await_count == 2
        # The full text is persisted as the bot message, split into ordered bubbles.
        for call in update.await_args_list:
            request = call.args[0]
            assert request.messages[0].response == TEXT
            assert request.messages[0].message_id
        assert publish.await_count == 2
        first_publish = publish.await_args_list[0].args
        assert first_publish[0] == ConversationSource.TELEGRAM
        assert first_publish[1] == USER_ID
        assert first_publish[2] == ["Report is ready.", "It has 3 pages."]

    async def test_failed_publish_is_logged_not_raised(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="tg-conv")),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.FAILED),
            ),
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT
            )

    async def test_a_failing_platform_does_not_block_the_other(self) -> None:
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(
                f"{MODULE}.BotService.get_or_create_session",
                AsyncMock(side_effect=[RuntimeError("mongo down"), "sl-conv"]),
            ),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as publish,
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT
            )

        # Telegram failed, Slack still delivered.
        assert publish.await_count == 1
        assert publish.await_args.args[0] == ConversationSource.SLACK


class TestVariantBreakTokens:
    async def test_new_line_break_variant_splits_bubbles_and_never_ships_literally(self) -> None:
        """The model sometimes emits <NEW_LINE_BREAK> instead of the canonical
        <NEW_MESSAGE_BREAK>. The variant must split bubbles exactly like the
        canonical token and must never reach a platform as literal text."""
        variant = "<NEW_LINE_BREAK>"
        text = f"Report is ready.{variant}It has 3 pages."

        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms",
                AsyncMock(return_value={"telegram": {"platformUserId": "tg-123"}}),
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="tg-conv")),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as publish,
        ):
            await deliver_workflow_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=text
            )

        bubbles = publish.await_args.args[2]
        assert bubbles == ["Report is ready.", "It has 3 pages."]
        for bubble in bubbles:
            assert "NEW_LINE" not in bubble
            assert "<NEW" not in bubble
