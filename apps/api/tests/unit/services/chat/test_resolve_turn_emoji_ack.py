"""resolve_turn_emoji_ack — classifying an interactive turn's final comms reply into the message stamp the saved turn should carry.

A comms REACT: <emoji> control line resolves the turn to a one-emoji acknowledgment of the user's
message; anything else passes through as a plain text turn.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.chat import ConversationSource
from app.constants.comms import DISPATCH_ACK_EMOJI
from app.models.chat_models import MessageKind
from app.services.chat.stream import (
    _save_reply,
    _StreamState,
    resolve_turn_emoji_ack,
    silent_dispatch_ack,
)

pytestmark = pytest.mark.unit


class TestResolveTurnEmojiAck:
    def test_react_directive_resolves_to_emoji_ack_stamped_on_user_message(
        self,
    ) -> None:
        message, kind, reacts_to = resolve_turn_emoji_ack("REACT: 😎", "umsg_1")
        assert message == "😎"
        assert kind is MessageKind.EMOJI_ACK
        assert reacts_to == "umsg_1"

    def test_react_payload_with_message_break_resolves_clean(self) -> None:
        message, kind, _ = resolve_turn_emoji_ack("REACT: 👍<NEW_MESSAGE_BREAK>", "umsg_1")
        assert message == "👍"
        assert kind is MessageKind.EMOJI_ACK

    def test_plain_reply_passes_through_unchanged(self) -> None:
        message, kind, reacts_to = resolve_turn_emoji_ack("Booked your 9am flight.", "umsg_1")
        assert message == "Booked your 9am flight."
        assert kind is MessageKind.TEXT
        assert reacts_to is None

    def test_empty_reply_passes_through(self) -> None:
        message, kind, reacts_to = resolve_turn_emoji_ack("", "umsg_1")
        assert message == ""
        assert kind is MessageKind.TEXT
        assert reacts_to is None

    @pytest.mark.regression
    def test_a_reaction_beside_a_message_saves_the_message_alone(self) -> None:
        message, kind, reacts_to = resolve_turn_emoji_ack(
            "On it.<NEW_MESSAGE_BREAK><EMOJI>👍</EMOJI>", "umsg_1"
        )
        assert (message, kind, reacts_to) == ("On it.", MessageKind.TEXT, None)

    def test_a_live_silence_resolves_to_an_empty_reply_never_the_tag(self) -> None:
        """The stream never showed the tag, so the saved turn must not either; empty hands it to the empty-reply fallback."""
        message, kind, reacts_to = resolve_turn_emoji_ack(
            "<SILENCE>routine refresh</SILENCE>", "umsg_1"
        )
        assert message == ""
        assert kind is MessageKind.TEXT
        assert reacts_to is None


class TestSilentDispatchAck:
    """A hand-off comms stays silent about is acknowledged by GAIA, per surface, never by comms' words."""

    @pytest.mark.parametrize(
        "source",
        [ConversationSource.WHATSAPP, ConversationSource.TELEGRAM, ConversationSource.SLACK],
    )
    def test_a_chat_app_gets_a_reaction_on_the_users_message(
        self, source: ConversationSource
    ) -> None:
        assert silent_dispatch_ack(source.value, "umsg_1") == (
            DISPATCH_ACK_EMOJI,
            MessageKind.EMOJI_ACK,
            "umsg_1",
        )

    @pytest.mark.parametrize(
        "source", [None, ConversationSource.WEB.value, ConversationSource.DESKTOP.value]
    )
    def test_an_app_surface_gets_the_accepted_chip_and_no_text(self, source: str | None) -> None:
        assert silent_dispatch_ack(source, "umsg_1") == ("", MessageKind.ACCEPTED, None)


class TestSavedSilentDispatch:
    """A hand-off the turn stayed silent about is saved as the ack its surface shows, never as the empty-reply fallback."""

    @staticmethod
    async def _save(*, delegated: bool, source: str, reply: str) -> AsyncMock:
        state = _StreamState(turn_id="umsg_1")
        state.delegated, state.source, state.complete_message = delegated, source, reply
        saved = AsyncMock()
        with (
            patch(
                "app.services.chat.stream.recover_stream_state",
                AsyncMock(return_value=(reply, state.tool_data)),
            ),
            patch("app.services.chat.stream.save_bot_reply", saved),
            patch("app.services.chat.stream.capture"),
        ):
            await _save_reply(
                "s1", AsyncMock(), AsyncMock(user_id="6812f0b3c9a14e2b7d5a91cc"), "c1", state
            )
        return saved

    async def test_the_web_saves_the_accepted_stamp_with_no_text(self) -> None:
        saved = await self._save(
            delegated=True, source="web", reply="<SILENCE>handed off</SILENCE>"
        )

        reply = saved.await_args.kwargs["reply"]
        assert (reply.complete_message, reply.kind) == ("", MessageKind.ACCEPTED)

    async def test_a_chat_app_saves_the_reaction(self) -> None:
        saved = await self._save(delegated=True, source="whatsapp", reply="")

        reply = saved.await_args.kwargs["reply"]
        assert (reply.complete_message, reply.kind, reply.reacts_to_message_id) == (
            DISPATCH_ACK_EMOJI,
            MessageKind.EMOJI_ACK,
            "umsg_1",
        )

    async def test_a_silence_with_nothing_handed_off_is_not_acknowledged(self) -> None:
        saved = await self._save(delegated=False, source="web", reply="<SILENCE>x</SILENCE>")

        assert saved.await_args.kwargs["reply"].kind is MessageKind.TEXT
