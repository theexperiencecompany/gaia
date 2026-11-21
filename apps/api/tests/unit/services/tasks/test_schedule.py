"""A repeat rule's next occurrence: zones, offsets, shortcuts, anchors and DST."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine

from app.services.tasks.schedule import next_occurrence

KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")


class TestCron:
    def test_a_stored_offset_reads_like_its_zone(self) -> None:
        """Regression: +05:30 once crashed ZoneInfo and fell back to UTC."""
        for zone in ("+05:30", "Asia/Kolkata"):
            next_run = next_occurrence("0 9 * * *", zone)
            assert next_run is not None
            assert (next_run.hour, next_run.minute) == (3, 30)

    def test_no_zone_reads_the_rule_in_utc(self) -> None:
        next_run = next_occurrence("0 9 * * *", None)
        assert next_run is not None
        assert (next_run.hour, next_run.minute) == (9, 0)

    def test_the_local_hour_holds_across_a_dst_change(self) -> None:
        with time_machine.travel(datetime(2025, 3, 8, 20, 0, tzinfo=UTC), tick=False):
            next_run = next_occurrence("0 8 * * *", "America/New_York")
        assert next_run == datetime(2025, 3, 9, 12, 0, tzinfo=UTC)

    def test_an_unreadable_rule_has_no_next_occurrence(self) -> None:
        assert next_occurrence("not-a-rule", "UTC") is None


class TestShortcuts:
    @pytest.mark.parametrize(
        ("rule", "step"), [("every_1h", timedelta(hours=1)), ("every_4h", timedelta(hours=4))]
    )
    def test_an_interval_steps_from_now(self, rule: str, step: timedelta) -> None:
        with time_machine.travel(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), tick=False):
            assert next_occurrence(rule) == datetime(2026, 1, 5, 10, 0, tzinfo=UTC) + step

    @pytest.mark.parametrize(
        ("rule", "step"), [("daily", timedelta(days=1)), ("weekly", timedelta(weeks=1))]
    )
    def test_without_an_anchor_it_steps_from_now(self, rule: str, step: timedelta) -> None:
        with time_machine.travel(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), tick=False):
            assert (
                next_occurrence(rule, "Asia/Kolkata")
                == datetime(2026, 1, 5, 10, 0, tzinfo=UTC) + step
            )

    def test_daily_keeps_the_anchors_local_time(self) -> None:
        anchor = datetime(2026, 1, 2, 8, 0, tzinfo=KOLKATA)
        with time_machine.travel(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), tick=False):
            next_run = next_occurrence("daily", "Asia/Kolkata", anchor=anchor)
        assert next_run == datetime(2026, 1, 6, 8, 0, tzinfo=KOLKATA)

    def test_weekly_keeps_the_weekday_and_local_time(self) -> None:
        anchor = datetime(2025, 12, 1, 7, 45, tzinfo=KOLKATA)
        with time_machine.travel(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), tick=False):
            next_run = next_occurrence("weekly", "Asia/Kolkata", anchor=anchor)
        assert next_run == datetime(2026, 1, 12, 7, 45, tzinfo=KOLKATA)

    def test_an_anchor_still_ahead_is_kept(self) -> None:
        anchor = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
        with time_machine.travel(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), tick=False):
            assert next_occurrence("daily", "UTC", anchor=anchor) == anchor

    def test_an_anchor_at_now_moves_a_full_step(self) -> None:
        """With < instead of <=, the next run is now and the job re-fires in a tight loop."""
        now = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
        with time_machine.travel(now, tick=False):
            assert next_occurrence("daily", "UTC", anchor=now) == now + timedelta(days=1)

    def test_daily_across_a_dst_change_holds_the_wall_clock(self) -> None:
        anchor = datetime(2025, 3, 8, 8, 0, tzinfo=NEW_YORK)
        with time_machine.travel(datetime(2025, 3, 8, 20, 0, tzinfo=UTC), tick=False):
            next_run = next_occurrence("daily", "America/New_York", anchor=anchor)
        assert next_run == datetime(2025, 3, 9, 12, 0, tzinfo=UTC)
