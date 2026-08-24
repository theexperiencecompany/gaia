"""Bubble-break sentinel parsing — every spelling the model actually emits."""

import re

import pytest

from app.utils.message_breaks import (
    _OPEN,
    _SENTINEL_WORD_SEQUENCES,
    MESSAGE_BREAK_SENTINEL_RE,
    PARTIAL_MESSAGE_BREAK_RE,
    _partial_sequence,
    _word_prefixes,
    split_message_bubbles,
    strip_partial_message_break,
)


#: Every non-empty prefix of a spelling's underscore-joined form, e.g. for
#: ("NEW", "MESSAGE") that is "N", "NE", "NEW", "NEW_", "NEW_M", ... "NEW_MESSAGE".
def _spelling_prefixes(words: tuple[str, ...]) -> list[str]:
    spelling = "_".join(words)
    return [spelling[: i + 1] for i in range(len(spelling))]


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


class TestPrefixBuilders:
    """``_word_prefixes`` and ``_partial_sequence`` run only at import time, to
    build the module-level compiled constants — no test exercises them through
    any public function, so a mutation of either can only be observed by
    calling them directly and asserting on what they return."""

    def test_word_prefixes_matches_every_non_empty_prefix(self) -> None:
        pattern = re.compile(_word_prefixes("NEW"))
        for prefix in ("N", "NE", "NEW"):
            assert pattern.fullmatch(prefix), prefix

    @pytest.mark.parametrize("text", ["", "E", "EW", "NEWS", "W"])
    def test_word_prefixes_rejects_non_prefixes(self, text: str) -> None:
        pattern = re.compile(_word_prefixes("NEW"))
        assert pattern.fullmatch(text) is None

    def test_word_prefixes_of_empty_word_is_empty_string(self) -> None:
        assert _word_prefixes("") == ""

    @pytest.mark.parametrize(
        "words", [*_SENTINEL_WORD_SEQUENCES, ("NEW",)], ids=lambda w: "_".join(w)
    )
    def test_partial_sequence_matches_every_prefix_of_the_spelling(
        self, words: tuple[str, ...]
    ) -> None:
        pattern = re.compile(_partial_sequence(words))
        for prefix in _spelling_prefixes(words):
            assert pattern.fullmatch(prefix), prefix

    @pytest.mark.parametrize(
        "words", [*_SENTINEL_WORD_SEQUENCES, ("NEW",)], ids=lambda w: "_".join(w)
    )
    def test_partial_sequence_rejects_empty_string(self, words: tuple[str, ...]) -> None:
        assert re.compile(_partial_sequence(words)).fullmatch("") is None

    def test_partial_sequence_rejects_a_non_prefix(self) -> None:
        pattern = re.compile(_partial_sequence(("NEW", "MESSAGE", "BREAK")))
        for text in ("NEWX", "NEW_MESSAGX", "MESSAGE"):
            assert pattern.fullmatch(text) is None, text

    @pytest.mark.parametrize(
        "words", [*_SENTINEL_WORD_SEQUENCES, ("NEW",)], ids=lambda w: "_".join(w)
    )
    def test_partial_sequence_emits_only_single_character_literals(
        self, words: tuple[str, ...]
    ) -> None:
        """The builder assembles one character at a time (see its docstring); a
        run of two or more literal letters means a placeholder or a stray
        ``None``/``str(None)`` leaked into the generated pattern instead of a
        real per-character prefix."""
        pattern_source = _partial_sequence(words)
        assert re.findall(r"(?<!\\)[A-Za-z]{2,}", pattern_source) == []

    def test_word_prefixes_emits_only_single_character_literals(self) -> None:
        assert re.findall(r"(?<!\\)[A-Za-z]{2,}", _word_prefixes("MESSAGE")) == []

    def test_partial_message_break_re_rebuilds_to_the_same_meaning(self) -> None:
        """Rebuild the alternation from the live helpers and re-run the strip
        table through it, pinning the end-to-end meaning at test time too."""
        rebuilt = re.compile(
            _OPEN
            + "(?:"
            + "|".join(_partial_sequence(words) for words in _SENTINEL_WORD_SEQUENCES)
            + ")$",
            re.IGNORECASE,
        )
        cases = [
            "numbers<NEW_MESSAGE_B",
            "numbers<NEW_MESSAGE_BREA",
            "numbers<new_",
            "numbers<N",
            "a<NEW_MESSAGE_BREAK>",
            "if a <",
            "see <div",
        ]
        for text in cases:
            assert rebuilt.sub("", text) == PARTIAL_MESSAGE_BREAK_RE.sub("", text), text
