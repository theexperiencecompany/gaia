"""The user's clock: their zone, their local midnights and the day a due date falls on."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.helpers import user_clock

from app.services.briefing.clock import UserClock, due_on, resolve_clock
from app.services.briefing.fact_pool.pool import PoolContext
from app.services.briefing.fact_pool.render import context_block

CLOCK = user_clock("Asia/Kolkata", date(2026, 10, 14), 7)


class TestClock:
    def test_missing_timezone_is_utc(self) -> None:
        assert resolve_clock(None).tz is UTC

    def test_unknown_timezone_reads_as_utc_like_every_other_clock(self) -> None:
        assert resolve_clock("Nowhere/City").tz is UTC

    def test_a_stored_utc_offset_is_the_users_clock(self) -> None:
        clock = resolve_clock("+05:30")

        assert clock.now_local.utcoffset() == timedelta(hours=5, minutes=30)
        assert (
            context_block(
                PoolContext(
                    reader="Ada",
                    clock=clock,
                    calendar=0,
                    calendar_span="today",
                    done_since=clock.day_start(),
                )
            )
            .splitlines()[0]
            .endswith(", +05:30.")
        )

    def test_the_clock_reads_now_on_the_users_zone(self) -> None:
        clock = resolve_clock("Pacific/Kiritimati")

        assert clock.now_local.tzinfo == ZoneInfo("Pacific/Kiritimati")
        assert clock.date_str == clock.now_local.date().isoformat()
        assert clock.day_of_year == clock.now_local.timetuple().tm_yday

    def test_day_start_is_local_midnight_in_utc(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        clock = UserClock(
            tz=tz,
            now_local=datetime(2026, 10, 13, 9, 30, tzinfo=tz),
            date_str="2026-10-13",
            day_of_year=286,
        )

        assert clock.day_start() == datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
        assert clock.day_start(days_ago=1) == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)

    def test_day_start_is_expressed_in_utc(self) -> None:
        assert CLOCK.day_start().tzinfo is UTC

    @pytest.mark.parametrize(
        ("due_at", "said"),
        [
            (datetime(2026, 10, 14, 17, 0, tzinfo=UTC), "today"),
            (datetime(2026, 10, 14, 19, 0, tzinfo=UTC), "Thu Oct 15"),
            (datetime(2026, 10, 12, 6, 0, tzinfo=UTC), "Mon Oct 12"),
            (datetime(2026, 10, 9, 6, 0, tzinfo=UTC), "Oct 9"),
            (datetime(2025, 10, 9, 6, 0, tzinfo=UTC), "Oct 9, 2025"),
        ],
        ids=[
            "late-on-the-users-day",
            "past-the-users-midnight",
            "earlier-this-week",
            "last-week-has-no-weekday-to-misread",
            "another-year-says-its-year",
        ],
    )
    def test_a_due_date_is_said_on_the_users_own_day(self, due_at: datetime, said: str) -> None:
        assert due_on(due_at, CLOCK) == said
