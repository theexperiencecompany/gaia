"""When a streaming reply first showed, net of text the graph retracted."""

from datetime import UTC, datetime, timedelta

import time_machine

from app.services.chat.reply_visibility import ReplyVisibility

_START = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)
_LATER = _START + timedelta(seconds=10)


def test_nothing_has_shown_on_a_fresh_reply() -> None:
    assert ReplyVisibility().first_shown_at is None


def test_text_is_stamped_once_at_its_first_piece() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_text()
        clock.shift(timedelta(seconds=10))
        visibility.saw_text()

    assert visibility.first_shown_at == _START


def test_a_card_is_stamped_once_at_the_first_card() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_card()
        clock.shift(timedelta(seconds=10))
        visibility.saw_card()

    assert visibility.first_shown_at == _START


def test_retracted_text_no_longer_counts_as_shown() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False):
        visibility.saw_text()
        visibility.settle(discarded=True)

    assert visibility.first_shown_at is None


def test_kept_text_keeps_its_stamp_past_later_retracted_text() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_text()
        visibility.settle(discarded=False)
        clock.shift(timedelta(seconds=10))
        visibility.saw_text()
        visibility.settle(discarded=True)

    assert visibility.first_shown_at == _START


def test_a_card_survives_the_retraction_of_its_message() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_card()
        clock.shift(timedelta(seconds=10))
        visibility.saw_text()
        visibility.settle(discarded=True)

    assert visibility.first_shown_at == _START


def test_text_shown_before_a_card_dates_the_reply_once_kept() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_text()
        clock.shift(timedelta(seconds=10))
        visibility.saw_card()
        assert visibility.first_shown_at == _START
        visibility.settle(discarded=False)

    assert visibility.first_shown_at == _START


def test_text_after_a_retraction_dates_the_reply_from_when_it_showed() -> None:
    visibility = ReplyVisibility()
    with time_machine.travel(_START, tick=False) as clock:
        visibility.saw_text()
        visibility.settle(discarded=True)
        clock.shift(timedelta(seconds=10))
        visibility.saw_text()

    assert visibility.first_shown_at == _LATER
