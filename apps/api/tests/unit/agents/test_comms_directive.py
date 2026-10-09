"""Parsing comms' non-text turn outcomes (<SILENCE> / <EMOJI>) vs an ordinary reply."""

from itertools import pairwise

import pytest

from app.agents.core.comms_directive import (
    interpret_comms_output,
    visible_comms_text,
    visible_comms_text_so_far,
)
from app.constants.comms import CommsDirectiveKind
from app.constants.general import NEW_MESSAGE_BREAKER as BREAK
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

EMOJI_DIRECTIVE_CASES: list[tuple[str, str | None]] = [
    ("<EMOJI>👍</EMOJI>", "👍"),
    ("  <emoji> ✅ </emoji>  ", "✅"),
    ("<EMOJI>👍</EMOJI>\n", "👍"),
    ("<EMOJI>😎</EMOJI><NEW_MESSAGE_BREAK>", "😎"),
    ("<EMOJI></EMOJI>", None),
    ("<EMOJI> </EMOJI><NEW_MESSAGE_BREAK>", None),
    # A reaction must be an emoji: a word in the tag is not one, so the bubble stays text.
    ("<EMOJI>ok</EMOJI>", None),
    # Keycaps are an ASCII digit, #, or * plus U+FE0F U+20E3; still one emoji.
    ("<EMOJI>1\ufe0f\u20e3</EMOJI>", "1\ufe0f\u20e3"),
    ("<EMOJI>#\ufe0f\u20e3</EMOJI>", "#\ufe0f\u20e3"),
    ("<EMOJI>*\u20e3</EMOJI>", "*\u20e3"),
    ("<EMOJI>1</EMOJI>", None),
    ("<EMOJI>12\u20e3</EMOJI>", None),
    ("<EMOJI>thumbs up</EMOJI>", None),
    ("<EMOJI>👍 nice</EMOJI>", None),
    ("<EMOJI>👍</SILENCE>", None),
    ("<EMOJI>👍", None),
    ("<EMOJI>👍</EMOJI>\nand more", None),
    ("hello <EMOJI>👍</EMOJI>", None),
    # The pre-tag line format, still in comms' own history.
    ("REACT: 👍", "👍"),
    ("REACT: 😎<NEW_MESSAGE_BREAK>", "😎"),
    ("REACT: <NEW_MESSAGE_BREAK>", None),
    ("REACT: done", None),
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

    def test_a_directive_before_a_message_leaves_only_the_message(self) -> None:
        d = interpret_comms_output(
            f"<SILENCE>nothing new</SILENCE>{BREAK}Actually, one thing changed."
        )
        assert d.kind == CommsDirectiveKind.REPLY
        assert d.payload == "Actually, one thing changed."


PASSPORT = "Your passport expires in 13 days, on October 10, 2026. Please book your renewal."


class TestADirectiveBesideAReplyIsNeverDelivered:
    """A model that writes a message AND a directive bubble: the message goes out, the tag never does."""

    @pytest.mark.parametrize(
        "text",
        [
            f"{PASSPORT}{BREAK}<SILENCE>Passport expiry is within the 30-day threshold.</SILENCE>",
            f"{PASSPORT}{BREAK}<EMOJI>👍</EMOJI>{BREAK}",
            f"{PASSPORT}{BREAK}SILENCE: routine check",
            f"{PASSPORT}{BREAK}REACT: 👍",
        ],
    )
    def test_a_trailing_directive_bubble_is_dropped(self, text: str) -> None:
        d = interpret_comms_output(text)
        assert d.kind == CommsDirectiveKind.REPLY
        assert d.payload == PASSPORT

    def test_a_directive_in_the_middle_keeps_the_bubbles_around_it(self) -> None:
        d = interpret_comms_output(f"First.{BREAK}<SILENCE>x</SILENCE>{BREAK}Second.")
        assert d.payload == f"First.{BREAK}Second."

    def test_the_first_of_several_directives_wins(self) -> None:
        d = interpret_comms_output(f"<EMOJI>👍</EMOJI>{BREAK}<SILENCE>x</SILENCE>")
        assert (d.kind, d.payload) == (CommsDirectiveKind.REACT, "👍")

    def test_a_last_bubble_that_only_starts_like_a_tag_is_kept(self) -> None:
        """Held while streaming because it could have become one; once the reply ends, it is text."""
        d = interpret_comms_output(f"<SILENCE>x</SILENCE>{BREAK}Re")
        assert (d.kind, d.payload) == (CommsDirectiveKind.REPLY, "Re")

    async def test_the_dropped_directive_is_logged(self) -> None:
        async with captured_wide_event() as event:
            interpret_comms_output(f"{PASSPORT}{BREAK}<SILENCE>threshold</SILENCE>")

        (warning,) = event["warnings"]
        assert warning["msg"] == (
            f"{LogTag.AGENT} comms wrote a directive beside its reply; the directive was dropped"
        )
        assert warning["dropped_directives"] == [{"kind": "silence", "payload": "threshold"}]

    async def test_a_reply_with_no_directive_is_untouched(self) -> None:
        text = f"On it.{BREAK}Done.{BREAK}"
        async with captured_wide_event() as event:
            assert interpret_comms_output(text).payload == text
        assert "warnings" not in event


class TestVisibleCommsText:
    """What of a message streamed so far a user may see: never a directive bubble."""

    @pytest.mark.parametrize(
        ("text", "visible"),
        [
            ("", ""),
            ("Hel", "Hel"),
            ("Hello", "Hello"),
            ("Really", "Really"),
            ("Re", ""),
            ("Silence is golden", "Silence is golden"),
            ("<", ""),
            ("<EM", ""),
            ("<EMOJI>👍</EM", ""),
            ("<EMOJI>👍</EMOJI>", ""),
            ("  ", ""),
            ("<b>bold</b> reply", "<b>bold</b> reply"),
            ("<EMOJI>\n", "<EMOJI>\n"),
            ("<EMOJI>👍</EMOJI>\nand more", "<EMOJI>👍</EMOJI>\nand more"),
            ("Hello there.<NEW_MESS", "Hello there."),
            ("Hello there. <", "Hello there. "),
            (f"Hello there.{BREAK}", "Hello there."),
            (f"Hello there.{BREAK}<SIL", "Hello there."),
            (f"Hello there.{BREAK}<SILENCE>x</SILENCE>", "Hello there."),
            (f"Hello there.{BREAK}Si", "Hello there."),
            (f"Hello there.{BREAK}Sure", f"Hello there.{BREAK}Sure"),
            (f"<SILENCE>x</SILENCE>{BREAK}Actually", "Actually"),
            (f"A.{BREAK}<SILENCE>x</SILENCE>{BREAK}C", f"A.{BREAK}C"),
            (f"A.{BREAK}REACT: 👍{BREAK}", "A."),
            (f"A.{BREAK}{BREAK}C", f"A.{BREAK}C"),
        ],
    )
    def test_while_streaming(self, text: str, visible: str) -> None:
        assert visible_comms_text_so_far(text) == visible

    @pytest.mark.parametrize(
        ("text", "visible"),
        [
            ("Re", "Re"),
            ("<EMOJI>👍</EMOJI>", ""),
            ("<EMOJI></EMOJI>", "<EMOJI></EMOJI>"),
            ("SILENCE: routine", ""),
            (f"Hello there.{BREAK}<SILENCE>x</SILENCE>", "Hello there."),
            (f"Hello there.{BREAK}", "Hello there."),
            ("Hello there.<NEW_MESS", "Hello there."),
            (f"A.{BREAK}<EMOJI>👍</EMOJI>{BREAK}C", f"A.{BREAK}C"),
            (f"A.{BREAK}  {BREAK}C", f"A.{BREAK}C"),
        ],
    )
    def test_once_the_message_ended(self, text: str, visible: str) -> None:
        assert visible_comms_text(text) == visible

    def test_what_was_shown_is_always_a_prefix_of_what_is_shown_next(self) -> None:
        """Clients append each delta; text shown early and then retracted would stay on screen."""
        text = (
            f"Hi <b>there</b>.{BREAK}  <SILENCE>no</SILENCE>{BREAK}Re: your trip<NEW_LINE_BREAK>ok"
        )
        shown = [visible_comms_text_so_far(text[:end]) for end in range(len(text) + 1)]
        shown.append(visible_comms_text(text))
        for earlier, later in pairwise(shown):
            assert later.startswith(earlier)
        assert shown[-1] == f"Hi <b>there</b>.{BREAK}Re: your trip<NEW_LINE_BREAK>ok"
