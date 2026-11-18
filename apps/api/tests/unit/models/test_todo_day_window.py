"""TodoDayWindow: the one place a user's todo today, upcoming and overdue bounds are decided."""

from datetime import UTC, datetime, timedelta
import time

import pytest

from app.models.todo_models import TodoDayWindow
from app.utils.timezone import Timezone

IST = Timezone.parse("Asia/Kolkata")
NEW_YORK = Timezone.parse("America/New_York")


def test_ist_user_at_one_am_gets_their_local_day_not_utcs() -> None:
    one_am_ist = datetime(2026, 11, 17, 19, 30, tzinfo=UTC)

    window = TodoDayWindow.for_timezone(IST, one_am_ist)

    assert window.today_start == datetime(2026, 11, 17, 18, 30, tzinfo=UTC)
    assert window.tomorrow_start == datetime(2026, 11, 18, 18, 30, tzinfo=UTC)


def test_bounds_are_expressed_in_utc_not_the_host_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        window = TodoDayWindow.for_timezone(IST, datetime(2026, 11, 17, 19, 30, tzinfo=UTC))
    finally:
        monkeypatch.undo()
        time.tzset()

    assert {b.utcoffset() for b in (window.today_start, window.upcoming_end)} == {timedelta(0)}


def test_upcoming_is_the_seven_local_days_after_today() -> None:
    window = TodoDayWindow.for_timezone(IST, datetime(2026, 11, 17, 19, 30, tzinfo=UTC))

    assert window.upcoming.start == window.tomorrow_start
    assert window.upcoming_end == window.tomorrow_start + timedelta(days=7)


def test_today_range_ends_just_before_tomorrow_starts() -> None:
    window = TodoDayWindow.for_timezone(IST, datetime(2026, 11, 17, 19, 30, tzinfo=UTC))

    assert window.today.start == window.today_start
    assert window.today.end < window.tomorrow_start
    assert window.tomorrow_start - window.today.end == timedelta(microseconds=1)


def test_day_bounds_are_local_midnights_across_a_dst_change() -> None:
    # 2026-03-08 02:00 New York springs forward, so that local day is 23 hours long.
    window = TodoDayWindow.for_timezone(NEW_YORK, datetime(2026, 3, 7, 17, 0, tzinfo=UTC))

    assert window.tomorrow_start == datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    assert window.upcoming_end == datetime(2026, 3, 15, 4, 0, tzinfo=UTC)


def test_upcoming_days_widens_the_upcoming_window() -> None:
    window = TodoDayWindow.for_timezone(
        Timezone.utc(), datetime(2026, 11, 17, 12, 0, tzinfo=UTC), upcoming_days=3
    )

    assert window.upcoming_end == datetime(2026, 11, 21, tzinfo=UTC)


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="^TodoDayWindow needs a timezone-aware now$"):
        TodoDayWindow.for_timezone(IST, datetime(2026, 11, 17, 19, 30))
