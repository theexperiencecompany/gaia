"""The brief's one way to write a day, a time and a text's opening line."""

from datetime import date, datetime, time

import pytest

from app.services.briefing import formats

pytestmark = pytest.mark.unit

_SATURDAY = date(2026, 11, 14)


def test_a_day_is_its_short_weekday_its_month_and_its_unpadded_date() -> None:
    assert formats.day(date(2026, 11, 7)) == "Sat Nov 7"


def test_a_dated_day_carries_its_year() -> None:
    assert formats.dated(_SATURDAY) == "Sat Nov 14, 2026"


def test_the_quiet_note_spells_the_weekday_whole() -> None:
    assert formats.long_day(_SATURDAY) == "Saturday Nov 14"


def test_a_weekday_whole_and_short() -> None:
    assert (formats.weekday(_SATURDAY), formats.short_weekday(_SATURDAY)) == ("Saturday", "Sat")


@pytest.mark.parametrize(
    ("at", "said"),
    [(time(9, 5), "9:05 AM"), (time(16, 0), "4:00 PM"), (time(0, 30), "12:30 AM")],
)
def test_a_time_is_on_a_twelve_hour_clock_unpadded(at: time, said: str) -> None:
    assert formats.clock_time(at) == said


def test_a_moment_is_its_day_then_its_time() -> None:
    assert formats.moment(datetime(2026, 11, 14, 8, 0)) == "Sat Nov 14, 8:00 AM"


@pytest.mark.parametrize(
    ("text", "first"),
    [("\n\n  Two drafts are ready  \nThen the rest", "Two drafts are ready"), ("  \n\t\n", "")],
    ids=["first-non-blank", "no-line"],
)
def test_a_texts_opening_line_is_its_first_non_blank_line(text: str, first: str) -> None:
    assert formats.opening_line(text) == first
