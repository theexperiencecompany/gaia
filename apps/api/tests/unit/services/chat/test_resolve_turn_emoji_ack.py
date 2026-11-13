"""resolve_turn_emoji_ack — classifying an interactive turn's final comms reply into the message stamp the saved turn should carry.

A comms REACT: <emoji> control line resolves the turn to a one-emoji acknowledgment of the user's
message; anything else passes through as a plain text turn.
"""

import pytest

from app.models.chat_models import MessageKind
from app.services.chat.stream import resolve_turn_emoji_ack

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
