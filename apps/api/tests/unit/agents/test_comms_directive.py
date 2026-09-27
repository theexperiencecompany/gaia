"""Parsing comms' non-text turn outcomes (<SILENCE> / <EMOJI>) vs an ordinary reply."""

import pytest

from app.agents.core.comms_directive import could_become_comms_directive, interpret_comms_output
from app.constants.comms import CommsDirectiveKind

pytestmark = pytest.mark.unit

EMOJI_DIRECTIVE_CASES: list[tuple[str, str | None]] = [
    ("<EMOJI>👍</EMOJI>", "👍"),
    ("  <emoji> ✅ </emoji>  ", "✅"),
    ("<EMOJI>👍</EMOJI>\n", "👍"),
    ("<EMOJI>😎</EMOJI><NEW_MESSAGE_BREAK>", "😎"),
    ("<EMOJI></EMOJI>", None),
    ("<EMOJI> </EMOJI><NEW_MESSAGE_BREAK>", None),
    ("<EMOJI>👍</SILENCE>", None),
    ("<EMOJI>👍", None),
    ("<EMOJI>👍</EMOJI>\nand more", None),
    ("<EMOJI>👍</EMOJI><NEW_MESSAGE_BREAK>and more", None),
    ("hello <EMOJI>👍</EMOJI>", None),
    # The pre-tag line format, still in comms' own history.
    ("REACT: 👍", "👍"),
    ("REACT: 😎<NEW_MESSAGE_BREAK>", "😎"),
    ("REACT: <NEW_MESSAGE_BREAK>", None),
    ("REACTION: completed", None),
    ("Booked your 9am flight to Tokyo.", None),
]


class TestInterpretCommsOutput:
    def test_a_silence_reason_never_carries_the_bubble_separator(self) -> None:
        """The reason lands in activity.md and the logs; comms ends every reply with the separator."""
        d = interpret_comms_output("SILENCE: nothing new<NEW_MESSAGE_BREAK>")
        assert d.kind == CommsDirectiveKind.SILENCE
        assert d.payload == "nothing new"

    def test_silence_directive(self) -> None:
        d = interpret_comms_output(
            "<SILENCE>background calendar refresh, nothing new</SILENCE><NEW_MESSAGE_BREAK>"
        )
        assert d.kind == CommsDirectiveKind.SILENCE
        assert d.payload == "background calendar refresh, nothing new"

    def test_a_silence_without_a_reason_is_still_a_silence(self) -> None:
        assert interpret_comms_output("<SILENCE></SILENCE>").kind == CommsDirectiveKind.SILENCE

    def test_the_pre_tag_silence_line_is_still_a_silence(self) -> None:
        d = interpret_comms_output("SILENCE: no-op wake")
        assert d.kind == CommsDirectiveKind.SILENCE
        assert d.payload == "no-op wake"

    @pytest.mark.parametrize(("text", "emoji"), EMOJI_DIRECTIVE_CASES)
    def test_emoji_directive_table(self, text: str, emoji: str | None) -> None:
        d = interpret_comms_output(text)
        if emoji is None:
            assert d.kind == CommsDirectiveKind.REPLY
            assert d.payload == text
        else:
            assert d.kind == CommsDirectiveKind.REACT
            assert d.payload == emoji

    def test_multiline_message_is_never_a_directive(self) -> None:
        # A real reply that merely starts with a tag must not be mis-silenced —
        # the safe failure is "treat as reply", never drop a real message.
        text = "<SILENCE>is golden</SILENCE>\nBut here is the actual answer you asked for."
        d = interpret_comms_output(text)
        assert d.kind == CommsDirectiveKind.REPLY
        assert d.payload == text

    def test_a_directive_followed_by_another_bubble_is_a_reply(self) -> None:
        text = "<SILENCE>nothing new</SILENCE><NEW_MESSAGE_BREAK>Actually, one thing changed."
        assert interpret_comms_output(text).kind == CommsDirectiveKind.REPLY


class TestCouldBecomeCommsDirective:
    """The live stream holds a turn back while this is true, so no client ever sees a directive."""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "  ",
            "<",
            "<em",
            "<EMOJI>",
            "<EMOJI>👍",
            "<EMOJI>👍</EMO",
            "<EMOJI>👍</EMOJI>",
            "<EMOJI>👍</EMOJI>\n",
            "<EMOJI>👍</EMOJI><NEW_MESS",
            "<EMOJI>👍</EMOJI><NEW_MESSAGE_BREAK>",
            "<sil",
            "<SILENCE>nothing new",
            "<SILENCE>nothing new</SILENCE><NEW_MESSAGE_BREAK>",
            "REACT",
            "REACT: ",
            "REACT: 😎<NEW_MESSAGE_BREAK>",
            "Sil",
            "SILENCE: no-op",
        ],
    )
    def test_holds_a_turn_one_more_chunk_can_still_make_a_directive(self, text: str) -> None:
        assert could_become_comms_directive(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Hello",
            "Really interesting",
            "Silence is golden",
            "<b>bold</b> reply",
            "<EMOJI>\n",
            "<\nEMOJI>👍</EMOJI>",
            "<EMOJI>👍</EMOJI>\nand more",
            "<EMOJI>👍</EMOJI><NEW_MESSAGE_BREAK>and more",
            "<EMOJI></EMOJI><NEW_MESSAGE_BREAK>",
            "<SILENCE>nothing new</SILENCE><NEW_MESSAGE_BREAK>Actually, one thing changed.",
            "hello <EMOJI>👍</EMOJI>",
            "REACTION: completed",
        ],
    )
    def test_releases_a_turn_no_later_chunk_can_make_a_directive(self, text: str) -> None:
        assert could_become_comms_directive(text) is False
