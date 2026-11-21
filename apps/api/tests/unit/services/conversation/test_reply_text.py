"""bubble_deltas: the fewest deltas that carry a client from the bubbles it shows to the reply's now."""

import pytest

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.models.stream_events import MessageBoundaryPayload
from app.services.conversation.reply_text import ReplyText, bubble_deltas, screen_bubbles
from app.utils.errors import ShownTextTakenBackError
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER, BubbleTextDelta
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
    with pytest.raises(
        ShownTextTakenBackError,
        match="^a reply's bubbles would change text a client already showed$",
    ) as refused:
        bubble_deltas(shown, now)
    assert refused.value.meta == {"shown": list(shown), "now": list(now)}


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


def test_text_streamed_after_a_kept_message_opens_a_bubble_below_it() -> None:
    text = ReplyText.kept("an answer").take(ResponseEvent(response="more"))

    assert text.text == f"an answer{NEW_MESSAGE_BREAKER}more"
    assert text.shown == text.text


def test_nothing_kept_is_an_empty_reply_text() -> None:
    assert ReplyText.kept("") == ReplyText()


def test_a_reply_of_only_bubble_breaks_stores_and_shows_no_text() -> None:
    reply = ReplyText().take(ResponseEvent(response=NEW_MESSAGE_BREAKER * 9))

    assert reply.text == ""
    assert reply.shown == ""


#: The outcome note a finished work's report carries to comms, echoed back by the model.
ECHOED_NOTE = (
    "<delivery_instructions>\nOutcome: it needs their decision. Ask exactly the one "
    "question the result names and nothing else.\n</delivery_instructions>\n"
)


@pytest.mark.regression
def test_an_echoed_delivery_note_never_reaches_the_reply() -> None:
    """Regression: the step path lost the internal-tag backstop, so an echoed outcome note showed on screen."""
    reply = ReplyText().take(ResponseEvent(response=f"Expired.\n\n{ECHOED_NOTE}"))

    assert reply.text == "Expired."
    assert reply.shown == "Expired."


@pytest.mark.parametrize("into_note", [1, 6, 12, 40, len(ECHOED_NOTE) - 5])
def test_a_note_still_streaming_is_never_shown_and_shown_text_only_grows(into_note: int) -> None:
    said = "Expired. "
    cut = len(said) + into_note
    streamed = f"{said}{ECHOED_NOTE}Ask them."
    before = ReplyText().take(ResponseEvent(response=streamed[:cut]))
    after = before.take(ResponseEvent(response=streamed[cut:]))

    assert before.shown == "Expired."
    assert after.shown.startswith(before.shown)
    assert after.text == "Expired. \nAsk them."


def test_a_note_cut_off_before_it_closes_is_not_stored() -> None:
    reply = ReplyText().take(ResponseEvent(response=f"Expired.\n{ECHOED_NOTE[:60]}"))

    assert reply.text == "Expired."


def test_a_lookalike_tag_is_ordinary_text() -> None:
    reply = ReplyText().take(ResponseEvent(response="Use <deliverables> and a<b."))

    assert reply.text == "Use <deliverables> and a<b."
    assert reply.shown == reply.text


def test_a_bare_closing_tag_still_streaming_is_never_shown() -> None:
    before = ReplyText().take(ResponseEvent(response="Done.</delivery_instr"))
    after = before.take(ResponseEvent(response="uctions> More."))

    assert before.shown == "Done."
    assert after.shown.startswith(before.shown)
    assert after.text == "Done. More."


def test_a_note_left_open_at_a_message_boundary_hides_only_its_own_message() -> None:
    boundary = MessageBoundaryEvent(message_boundary=MessageBoundaryPayload(message_id="m1"))
    reply = (
        ReplyText()
        .take(ResponseEvent(response="Status.<delivery_instructions>internal"))
        .take(boundary)
        .take(ResponseEvent(response="Please choose a date."))
    )

    assert reply.text == f"Status.{NEW_MESSAGE_BREAKER}Please choose a date."
    assert reply.shown == reply.text


def test_a_message_that_was_only_an_open_note_opens_no_bubble() -> None:
    boundary = MessageBoundaryEvent(message_boundary=MessageBoundaryPayload(message_id="m1"))
    reply = (
        ReplyText()
        .take(ResponseEvent(response="<delivery_instructions>internal"))
        .take(boundary)
        .take(ResponseEvent(response="Hello."))
    )

    assert reply.text == "Hello."
