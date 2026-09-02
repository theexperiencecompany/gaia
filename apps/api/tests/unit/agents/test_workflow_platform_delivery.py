"""Behavior tests for app.agents.core.background.workflow_platform_delivery.

Locks: delivery only happens for linked, enabled bot platforms carrying a
platform user id; the notification text is split into bubbles on the break
sentinel; each platform gets a persisted bot message and one outbound publish;
and every failure path stays best-effort (logs, never raises, never blocks
sibling platforms).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background.workflow_platform_delivery import (
    _preferred_bot_platforms,
    deliver_result_to_platforms,
)
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.services.outbound_delivery import OutboundResult
from tests.helpers import captured_wide_event

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
    ORIGIN = 'workflow "Morning digest" (id wf-1)'

    async def test_blank_text_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock()) as linked,
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock()),
        ):
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text="   ", origin=self.ORIGIN
            )

        linked.assert_not_called()

    async def test_no_targets_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value={})),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock()) as session,
        ):
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
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
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
            )

        assert session.await_count == 2
        # The session must be resolved for THIS platform user and owner — a
        # wrong id here delivers someone else's conversation GAIA's message.
        first_session = session.await_args_list[0].kwargs
        assert first_session["platform"] == "telegram"
        assert first_session["platform_user_id"] == "tg-123"
        assert first_session["user"] == USER
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
        """A failed publish is swallowed — but observable: log.error lands in
        the wide event's errors[], naming the platform and conversation."""
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
            async with captured_wide_event() as event:
                await deliver_result_to_platforms(
                    user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
                )

        errors = [
            e
            for e in event["errors"]
            if e["msg"] == f"{LogTag.AGENT} workflow platform publish failed"
        ]
        assert {e["platform"] for e in errors} == {"telegram", "slack"}
        assert errors[0]["conversation_id"] == "tg-conv"

    async def test_exclude_source_drops_that_platform_from_the_fanout(self) -> None:
        """A result already delivered into the source conversation's platform must
        not be re-sent to that platform in the fan-out — but every other linked,
        enabled platform still receives it."""
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="sl-conv")),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as publish,
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text=TEXT,
                origin=self.ORIGIN,
                exclude_source=ConversationSource.TELEGRAM,
            )

        # Telegram was the source and is excluded; Slack still delivered.
        assert publish.await_count == 1
        assert publish.await_args.args[0] == ConversationSource.SLACK

    async def test_exclude_source_none_delivers_to_every_platform(self) -> None:
        """The default (no exclusion) reaches every linked, enabled platform —
        the filter must not drop a target when ``exclude_source`` is None."""
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(
                f"{MODULE}.BotService.get_or_create_session",
                AsyncMock(side_effect=["tg-conv", "sl-conv"]),
            ),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as publish,
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text=TEXT,
                origin=self.ORIGIN,
                exclude_source=None,
            )

        assert {call.args[0] for call in publish.await_args_list} == {
            ConversationSource.TELEGRAM,
            ConversationSource.SLACK,
        }

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
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
            )

        # Telegram failed, Slack still delivered.
        assert publish.await_count == 1
        assert publish.await_args.args[0] == ConversationSource.SLACK


class TestDeliveredResultsReachTheSessionThread:
    """A result pushed into a bot session must also land in that conversation's
    langgraph checkpoint thread — the Mongo save alone is invisible to the next
    turn, which reads its history from the checkpoint, so GAIA had no memory of
    results it had just sent to Telegram. The record carries the platform and
    origin (with machine ids) so a later turn can backtrack to the source."""

    ORIGIN = 'workflow "Morning digest" (id wf-1), tracked todo (id todo-9)'

    async def _deliver(self, publish_result: OutboundResult) -> AsyncMock:
        recorder = AsyncMock()
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms", AsyncMock(return_value=LINKED)
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value=PREFERENCES)),
            patch(
                f"{MODULE}.BotService.get_or_create_session",
                AsyncMock(side_effect=["tg-conv", "sl-conv"]),
            ),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(f"{MODULE}.publish_outbound_message", AsyncMock(return_value=publish_result)),
            patch(f"{MODULE}.record_platform_delivery", recorder),
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text=TEXT,
                origin=self.ORIGIN,
            )
        return recorder

    @pytest.mark.regression
    async def test_published_result_is_recorded_in_each_session_thread(self) -> None:
        record = await self._deliver(OutboundResult.PUBLISHED)

        # The checkpoint stores what the user actually saw — the outbound
        # bubbles joined with blank control tokens removed, not the raw
        # response containing <NEW_MESSAGE_BREAK>.
        delivered = "Report is ready.\n\nIt has 3 pages."
        recorded = {call.args for call in record.await_args_list}
        assert recorded == {
            (
                "tg-conv",
                f"[Delivered to the user on Telegram — result of {self.ORIGIN}]: {delivered}",
            ),
            ("sl-conv", f"[Delivered to the user on Slack — result of {self.ORIGIN}]: {delivered}"),
        }

    async def test_recorded_text_excludes_break_sentinel(self) -> None:
        """The sentinel is stripped before the checkpoint write — it never
        reaches the next turn's history as literal text."""
        record = await self._deliver(OutboundResult.PUBLISHED)
        for _, text in record.await_args_list:
            assert NEW_MESSAGE_BREAKER not in text
            assert "<NEW" not in text

    async def test_whatsapp_display_name_preserves_casing(self) -> None:
        """WhatsApp's display name is ``WhatsApp``, not ``Whatsapp`` — a
        ``.capitalize()`` fallback would be observable here."""
        recorder = AsyncMock()
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms",
                AsyncMock(return_value={"whatsapp": {"platformUserId": "wa-1"}}),
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="wa-conv")),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ),
            patch(f"{MODULE}.record_platform_delivery", recorder),
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text="hello",
                origin=self.ORIGIN,
            )
        assert recorder.await_args.args[1].startswith("[Delivered to the user on WhatsApp —")

    async def test_imessage_uses_capitalized_fallback(self) -> None:
        """iMessage has no entry in PLATFORM_DISPLAY_NAMES — the fallback
        ``source.value.capitalize()`` must be used rather than ``None``."""
        recorder = AsyncMock()
        with (
            patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms",
                AsyncMock(return_value={"imessage": {"platformUserId": "im-1"}}),
            ),
            patch(f"{MODULE}.fetch_channel_preferences", AsyncMock(return_value={})),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="im-conv")),
            patch(f"{MODULE}.update_messages", AsyncMock()),
            patch(
                f"{MODULE}.publish_outbound_message",
                AsyncMock(return_value=OutboundResult.PUBLISHED),
            ),
            patch(f"{MODULE}.record_platform_delivery", recorder),
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text="hello",
                origin=self.ORIGIN,
            )
        assert recorder.await_args.args[1].startswith("[Delivered to the user on Imessage —")

    @pytest.mark.regression
    async def test_a_result_that_was_not_delivered_is_not_recorded(self) -> None:
        record = await self._deliver(OutboundResult.FAILED)

        record.assert_not_called()


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
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text=text,
                origin='workflow "Morning digest" (id wf-1)',
            )

        bubbles = publish.await_args.args[2]
        assert bubbles == ["Report is ready.", "It has 3 pages."]
        for bubble in bubbles:
            assert "NEW_LINE" not in bubble
            assert "<NEW" not in bubble
