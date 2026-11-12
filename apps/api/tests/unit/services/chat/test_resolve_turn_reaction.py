"""resolve_turn_reaction: an interactive turn's final comms reply split into the text it saves and the emoji it reacts with."""

import pytest

from app.services.chat.stream import resolve_turn_reaction

pytestmark = pytest.mark.unit


class TestResolveTurnReaction:
    def test_a_react_directive_is_a_reaction_with_no_text(self) -> None:
        assert resolve_turn_reaction("REACT: 😎") == ("", "😎")

    def test_react_payload_with_message_break_resolves_clean(self) -> None:
        assert resolve_turn_reaction("REACT: 👍<NEW_MESSAGE_BREAK>") == ("", "👍")

    def test_plain_reply_passes_through_unchanged(self) -> None:
        assert resolve_turn_reaction("Booked your 9am flight.") == (
            "Booked your 9am flight.",
            None,
        )

    def test_empty_reply_passes_through(self) -> None:
        assert resolve_turn_reaction("") == ("", None)

    @pytest.mark.regression
    def test_a_reaction_beside_a_message_saves_the_message_alone(self) -> None:
        assert resolve_turn_reaction("On it.<NEW_MESSAGE_BREAK><EMOJI>👍</EMOJI>") == (
            "On it.",
            None,
        )

    def test_a_live_silence_resolves_to_an_empty_reply_never_the_tag(self) -> None:
        """The stream never showed the tag, so the saved turn must not either; empty hands it to the empty-reply fallback."""
        assert resolve_turn_reaction("<SILENCE>routine refresh</SILENCE>") == ("", None)
