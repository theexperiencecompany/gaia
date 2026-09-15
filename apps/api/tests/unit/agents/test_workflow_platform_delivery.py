"""Behavior tests for app.agents.core.background.workflow_platform_delivery.

Locks: a result goes to the ONE platform ``resolve_chat_channel`` picks; the
notification text is split into bubbles on the break sentinel; that platform
gets a persisted bot message and one outbound publish; the platform that
already has the result in its own conversation is never pinged again; and
every failure path stays best-effort (logs, never raises).
"""

from unittest.mock import AsyncMock, patch

from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from tests.helpers import captured_wide_event

MODULE = "app.agents.core.background.workflow_platform_delivery"

USER: dict = {"user_id": "user-1", "email": "u@gaia.local"}
USER_ID = "user-1"
TEXT = f"Report is ready.{NEW_MESSAGE_BREAKER}It has 3 pages."

TELEGRAM = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-123")


def _channel(channel: ChatChannel | None):
    return patch(f"{MODULE}.resolve_chat_channel", AsyncMock(return_value=channel))


class TestDeliverWorkflowResultToPlatforms:
    ORIGIN = 'workflow "Morning digest" (id wf-1)'

    async def test_blank_text_is_a_no_op(self) -> None:
        with _channel(TELEGRAM) as resolve:
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text="   ", origin=self.ORIGIN
            )

        resolve.assert_not_awaited()

    async def test_no_usable_platform_is_a_no_op(self) -> None:
        with (
            _channel(None),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock()) as session,
        ):
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
            )

        session.assert_not_called()

    async def test_channel_lookup_failure_is_logged_and_sends_nothing(self) -> None:
        with (
            patch(f"{MODULE}.resolve_chat_channel", AsyncMock(side_effect=RuntimeError("db down"))),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock()) as session,
        ):
            async with captured_wide_event() as event:
                await deliver_result_to_platforms(
                    user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
                )

        session.assert_not_called()
        assert {
            "msg": f"{LogTag.AGENT} workflow platform delivery: channel lookup failed",
            "error": "db down",
        } in event["errors"]

    async def test_happy_path_persists_and_publishes_to_the_one_platform(self) -> None:
        with (
            _channel(TELEGRAM) as resolve,
            patch(
                f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="tg-conv")
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

        resolve.assert_awaited_once_with(USER_ID)
        # The session must be resolved for THIS platform user and owner — a
        # wrong id here delivers someone else's conversation GAIA's message.
        session.assert_awaited_once()
        assert session.await_args.kwargs["platform"] == "telegram"
        assert session.await_args.kwargs["platform_user_id"] == "tg-123"
        assert session.await_args.kwargs["user"] == USER
        # A proactive delivery is a DM; on Discord and Slack a channel-keyed
        # session would be a different conversation than the user's DM thread.
        assert session.await_args.kwargs["is_dm"] is True
        # The full text is persisted as the bot message, split into ordered bubbles.
        update.assert_awaited_once()
        request = update.await_args.args[0]
        assert request.messages[0].response == TEXT
        assert request.messages[0].message_id
        publish.assert_awaited_once()
        assert publish.await_args.args == (
            ConversationSource.TELEGRAM,
            USER_ID,
            ["Report is ready.", "It has 3 pages."],
        )
        # The channel already resolved the account id; the publisher must not
        # read the user document again to recompute it.
        assert publish.await_args.kwargs == {"destination_override": "tg-123"}

    async def test_failed_publish_is_logged_not_raised(self) -> None:
        """A failed publish is swallowed — but observable: log.error lands in
        the wide event's errors[], naming the platform and conversation."""
        with (
            _channel(TELEGRAM),
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
        assert [e["platform"] for e in errors] == ["telegram"]
        assert errors[0]["conversation_id"] == "tg-conv"

    async def test_the_platform_that_already_has_the_result_is_not_pinged_again(self) -> None:
        """A reminder answered in the Telegram conversation is not re-sent to
        Telegram, and it does not go to a second platform either: the preferred
        platform already has it."""
        with (
            _channel(TELEGRAM),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock()) as session,
            patch(f"{MODULE}.publish_outbound_message", AsyncMock()) as publish,
        ):
            await deliver_result_to_platforms(
                user=USER,
                user_id=USER_ID,
                notification_text=TEXT,
                origin=self.ORIGIN,
                exclude_source=ConversationSource.TELEGRAM,
            )

        session.assert_not_called()
        publish.assert_not_called()

    async def test_a_result_from_another_platforms_conversation_still_reaches_the_preferred_one(
        self,
    ) -> None:
        with (
            _channel(TELEGRAM),
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
                notification_text=TEXT,
                origin=self.ORIGIN,
                exclude_source=ConversationSource.SLACK,
            )

        assert publish.await_args.args[0] == ConversationSource.TELEGRAM

    async def test_a_session_failure_is_logged_not_raised(self) -> None:
        with (
            _channel(TELEGRAM),
            patch(
                f"{MODULE}.BotService.get_or_create_session",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{MODULE}.publish_outbound_message", AsyncMock()) as publish,
        ):
            await deliver_result_to_platforms(
                user=USER, user_id=USER_ID, notification_text=TEXT, origin=self.ORIGIN
            )

        publish.assert_not_called()


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
            _channel(TELEGRAM),
            patch(f"{MODULE}.BotService.get_or_create_session", AsyncMock(return_value="tg-conv")),
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

    async def test_published_result_is_recorded_in_the_session_thread(self) -> None:
        record = await self._deliver(OutboundResult.PUBLISHED)

        # The checkpoint stores what the user actually saw — the outbound
        # bubbles joined with blank control tokens removed, not the raw
        # response containing <NEW_MESSAGE_BREAK>.
        delivered = "Report is ready.\n\nIt has 3 pages."
        record.assert_awaited_once_with(
            "tg-conv",
            f"[Delivered to the user on Telegram — result of {self.ORIGIN}]: {delivered}",
        )

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
            _channel(ChatChannel(source=ConversationSource.WHATSAPP, platform_user_id="wa-1")),
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

    async def test_imessage_is_spelled_the_way_apple_spells_it(self) -> None:
        """iMessage is the one platform whose display name is not a plain
        capitalization, so the map must carry it rather than fall back."""
        recorder = AsyncMock()
        with (
            _channel(ChatChannel(source=ConversationSource.IMESSAGE, platform_user_id="im-1")),
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
        assert recorder.await_args.args[1].startswith("[Delivered to the user on iMessage —")

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
            _channel(ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-123")),
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
