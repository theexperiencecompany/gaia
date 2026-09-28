"""Parsing comms' non-text turn outcomes (SILENCE / REACT) vs an ordinary reply."""

import pytest

from app.agents.core.comms_directive import interpret_comms_output
from app.constants.comms import CommsDirectiveKind

pytestmark = pytest.mark.unit

# Same table as REACT_DIRECTIVE_CASES in libs/shared/ts/src/bots/utils/react-directive.test.ts —
# change both together, or bots and backend disagree on what gets an emoji_ack.
REACT_DIRECTIVE_CASES: list[tuple[str, str | None]] = [
    ("REACT: 👍", "👍"),
    ("  react:   ✅  ", "✅"),
    ("REACT:👍", "👍"),
    ("REACT: 👍\n", "👍"),
    ("REACT: 😎<NEW_MESSAGE_BREAK>", "😎"),
    ("REACT: <NEW_MESSAGE_BREAK>", None),
    ("REACT:", None),
    ("REACT:   ", None),
    ("REACT: 👍\nand more", None),
    ("REACTION: completed", None),
    ("hello REACT: 👍", None),
    ("Booked your 9am flight to Tokyo.", None),
]


class TestInterpretCommsOutput:
    def test_a_silence_reason_never_carries_the_bubble_separator(self) -> None:
        """The reason lands in activity.md and the logs; comms ends every reply with the separator."""
        d = interpret_comms_output("SILENCE: nothing new<NEW_MESSAGE_BREAK>")
        assert d.kind == CommsDirectiveKind.SILENCE
        assert d.payload == "nothing new"

    def test_silence_directive(self) -> None:
        d = interpret_comms_output("SILENCE: background calendar refresh, nothing new")
        assert d.kind == CommsDirectiveKind.SILENCE
        assert d.payload == "background calendar refresh, nothing new"

    @pytest.mark.parametrize(("text", "emoji"), REACT_DIRECTIVE_CASES)
    def test_react_directive_table(self, text: str, emoji: str | None) -> None:
        d = interpret_comms_output(text)
        if emoji is None:
            assert d.kind == CommsDirectiveKind.REPLY
            assert d.payload == text
        else:
            assert d.kind == CommsDirectiveKind.REACT
            assert d.payload == emoji

    def test_multiline_message_is_never_a_directive(self) -> None:
        # A real reply that merely starts with the word must not be mis-silenced —
        # the safe failure is "treat as reply", never drop a real message.
        text = "SILENCE: is golden.\nBut here is the actual answer you asked for."
        d = interpret_comms_output(text)
        assert d.kind == CommsDirectiveKind.REPLY
        assert d.payload == text
