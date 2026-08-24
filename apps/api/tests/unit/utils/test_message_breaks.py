"""Bubble-break sentinel parsing — every spelling the model actually emits."""

import pytest

from app.utils.message_breaks import (
    MESSAGE_BREAK_SENTINEL_RE,
    split_message_bubbles,
    strip_partial_message_break,
)


class TestSentinelPattern:
    @pytest.mark.parametrize(
        "token",
        [
            "<NEW_MESSAGE_BREAK>",
            "<NEW_LINE_BREAK>",
            "< NEW_MESSAGE_BREAK >",
            "<new_message_break>",
            "</NEW_MESSAGE_BREAK>",
            "<NEW_MESSAGE_BREAK/>",
            "[NEW_MESSAGE_BREAK]",
            "[new_line_break]",
            "<NEW MESSAGE BREAK>",
            "<NEW-MESSAGE-BREAK>",
        ],
    )
    def test_matches_every_spelling(self, token: str) -> None:
        assert MESSAGE_BREAK_SENTINEL_RE.fullmatch(token) is not None

    @pytest.mark.parametrize(
        "text",
        ["<NEW_MESSAGE>", "<BREAK>", "<br>", "plain text", "<NEW_MESSAGE_BREA"],
    )
    def test_rejects_non_sentinels(self, text: str) -> None:
        assert MESSAGE_BREAK_SENTINEL_RE.search(text) is None


class TestStripPartialMessageBreak:
    @pytest.mark.parametrize(
        "text",
        ["numbers<NEW_MESSAGE_B", "numbers<NEW_MESSAGE_BREA", "numbers<new_", "numbers<N"],
    )
    def test_strips_trailing_partial(self, text: str) -> None:
        assert strip_partial_message_break(text) == "numbers"

    def test_keeps_complete_sentinel(self) -> None:
        assert strip_partial_message_break("a<NEW_MESSAGE_BREAK>") == "a<NEW_MESSAGE_BREAK>"

    def test_keeps_a_lone_trailing_bracket(self) -> None:
        """A bare ``<`` carries no sentinel evidence — eating it would corrupt
        ordinary text (a code snippet ending in ``<``)."""
        assert strip_partial_message_break("if a <") == "if a <"

    def test_keeps_unrelated_trailing_tag(self) -> None:
        assert strip_partial_message_break("see <div") == "see <div"


class TestSplitMessageBubbles:
    def test_splits_on_every_variant(self) -> None:
        text = "one<NEW_MESSAGE_BREAK>two[NEW_LINE_BREAK]three</NEW_MESSAGE_BREAK>four"
        assert split_message_bubbles(text) == ["one", "two", "three", "four"]

    def test_drops_empty_and_trims(self) -> None:
        text = "  one  <NEW_MESSAGE_BREAK><NEW_MESSAGE_BREAK>  two \n"
        assert split_message_bubbles(text) == ["one", "two"]

    def test_strips_trailing_partial_token(self) -> None:
        assert split_message_bubbles("your numbers<NEW_MESSAGE_B") == ["your numbers"]

    def test_empty_text_yields_no_bubbles(self) -> None:
        assert split_message_bubbles("") == []
        assert split_message_bubbles("<NEW_MESSAGE_BREAK>") == []

    def test_text_without_sentinel_is_one_bubble(self) -> None:
        assert split_message_bubbles("just one thing") == ["just one thing"]
