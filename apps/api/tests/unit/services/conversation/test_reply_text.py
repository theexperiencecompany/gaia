"""bubble_deltas: the fewest deltas that carry a client from the bubbles it shows to the reply's now."""

import pytest

from app.services.conversation.reply_text import bubble_deltas, screen_bubbles
from app.utils.errors import ShownTextTakenBackError
from shared.py.conversation_wire import BubbleTextDelta
from tests.helpers import TEST_FILE_LINKS


@pytest.mark.parametrize(
    ("shown", "now", "deltas"),
    [
        ((), (), []),
        ((), ("hi",), [BubbleTextDelta(bubble=0, text="hi")]),
        (("he",), ("hello",), [BubbleTextDelta(bubble=0, text="llo")]),
        (("hi",), ("hi",), []),
        (("hi",), ("hi", "there"), [BubbleTextDelta(bubble=1, text="there")]),
        (
            ("a", "b"),
            ("a", "bc", "d"),
            [BubbleTextDelta(bubble=1, text="c"), BubbleTextDelta(bubble=2, text="d")],
        ),
    ],
)
def test_streamed_text_only_appends_to_the_last_bubble_or_opens_later_ones(
    shown: tuple[str, ...], now: tuple[str, ...], deltas: list[BubbleTextDelta]
) -> None:
    assert bubble_deltas(shown, now) == deltas


@pytest.mark.parametrize(
    ("shown", "now"),
    [
        (("hello",), ("help",)),
        (("a", "b"), ("x", "b")),
        (("a", "b"), ("x", "bc")),
        (("a", "b", "c"), ("a", "x", "cd")),
        (("ab", "c"), ("ab", "x", "c")),
    ],
)
def test_bubbles_that_would_change_shown_text_are_refused(
    shown: tuple[str, ...], now: tuple[str, ...]
) -> None:
    with pytest.raises(ShownTextTakenBackError):
        bubble_deltas(shown, now)


@pytest.mark.parametrize(
    ("shown", "now"),
    [
        (("hello",), ("hel",)),
        (("a", "b"), ("a",)),
        (("a", "b"), ("a", "")),
        (("hi",), ()),
    ],
)
def test_text_taken_back_to_what_is_shown_stays_until_its_replacement_reads_past_it(
    shown: tuple[str, ...], now: tuple[str, ...]
) -> None:
    assert bubble_deltas(shown, now) == []


def test_reply_text_splits_into_its_bubbles() -> None:
    assert screen_bubbles("first<NEW_MESSAGE_BREAK>second", "c1", TEST_FILE_LINKS) == (
        "first",
        "second",
    )


def test_a_file_the_reply_names_links_to_its_own_conversation() -> None:
    assert screen_bubbles("See [report](artifacts/report.pdf)", "c1", TEST_FILE_LINKS) == (
        "See [report](https://gaia.test/c/c1)",
    )
