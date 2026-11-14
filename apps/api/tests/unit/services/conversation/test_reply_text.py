"""bubble_deltas: the fewest deltas that carry a client from the bubbles it shows to the reply's now."""

import pytest

from app.services.conversation.reply_text import bubble_deltas
from shared.py.conversation_wire import BubblesDelta, BubbleTextDelta


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
        (("a", "b"), ("a",)),
        (("a", "b", "c"), ("a", "x", "cd")),
        (("ab", "c"), ("ab", "x", "c")),
    ],
)
def test_text_the_model_took_back_replaces_every_bubble(
    shown: tuple[str, ...], now: tuple[str, ...]
) -> None:
    assert bubble_deltas(shown, now) == [BubblesDelta(bubbles=now)]
