"""The quiet-hours policy: when a proactive chat message may reach the user."""

from datetime import UTC, datetime

import pytest

from app.constants.notifications import ProactiveMessageClass
from app.models.notification.notification_models import QuietHours
from app.services.delivery.quiet_hours import (
    QUIET_HOURS_EXEMPT,
    contains_hour,
    held_until,
    quiet_window_end,
)

OVERNIGHT = QuietHours(start_hour=22, end_hour=8)
DAYTIME = QuietHours(start_hour=13, end_hour=15)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


class TestContainsHour:
    @pytest.mark.parametrize(
        ("hour", "inside"),
        [(21, False), (22, True), (23, True), (0, True), (7, True), (8, False), (12, False)],
    )
    def test_a_window_spanning_midnight(self, hour: int, inside: bool) -> None:
        assert contains_hour(OVERNIGHT, hour) is inside

    @pytest.mark.parametrize(("hour", "inside"), [(12, False), (13, True), (14, True), (15, False)])
    def test_a_window_within_one_day_ends_before_its_end_hour(
        self, hour: int, inside: bool
    ) -> None:
        assert contains_hour(DAYTIME, hour) is inside


class TestQuietWindowEnd:
    @pytest.mark.parametrize(
        ("now", "end"),
        [
            # Before midnight: the window ends the next morning.
            (_utc(2026, 10, 14, 22, 0), _utc(2026, 10, 15, 8, 0)),
            (_utc(2026, 10, 14, 23, 59), _utc(2026, 10, 15, 8, 0)),
            # After midnight: the window ends the same morning.
            (_utc(2026, 10, 15, 0, 0), _utc(2026, 10, 15, 8, 0)),
            (_utc(2026, 10, 15, 7, 59), _utc(2026, 10, 15, 8, 0)),
        ],
    )
    def test_a_window_spanning_midnight_ends_at_its_end_hour(
        self, now: datetime, end: datetime
    ) -> None:
        assert quiet_window_end(OVERNIGHT, "UTC", now) == end

    @pytest.mark.parametrize(
        "now",
        [_utc(2026, 10, 15, 8, 0), _utc(2026, 10, 15, 12, 0), _utc(2026, 10, 14, 21, 59)],
    )
    def test_outside_the_window_nothing_is_held(self, now: datetime) -> None:
        assert quiet_window_end(OVERNIGHT, "UTC", now) is None

    def test_a_window_within_one_day(self) -> None:
        assert quiet_window_end(DAYTIME, "UTC", _utc(2026, 10, 15, 14, 30)) == _utc(
            2026, 10, 15, 15, 0
        )
        assert quiet_window_end(DAYTIME, "UTC", _utc(2026, 10, 15, 15, 0)) is None
        assert quiet_window_end(DAYTIME, "UTC", _utc(2026, 10, 15, 12, 59)) is None

    def test_the_window_is_on_the_users_clock_not_utc(self) -> None:
        # 17:30 UTC is 23:00 in Kolkata (UTC+5:30): inside, ending 08:00 IST = 02:30 UTC.
        now = _utc(2026, 10, 14, 17, 30)
        assert quiet_window_end(OVERNIGHT, "Asia/Kolkata", now) == _utc(2026, 10, 15, 2, 30)
        # The same instant is 17:30 on a UTC clock: outside.
        assert quiet_window_end(OVERNIGHT, "UTC", now) is None

    def test_a_user_west_of_utc_crosses_midnight_on_their_own_date(self) -> None:
        # 05:00 UTC on Oct 15 is 22:00 on Oct 14 in Los Angeles (PDT, UTC-7).
        now = _utc(2026, 10, 15, 5, 0)
        assert quiet_window_end(OVERNIGHT, "America/Los_Angeles", now) == _utc(2026, 10, 15, 15, 0)

    def test_the_end_is_the_top_of_the_hour_whatever_the_seconds(self) -> None:
        now = datetime(2026, 10, 15, 7, 59, 59, 999999, tzinfo=UTC)
        assert quiet_window_end(OVERNIGHT, "UTC", now) == _utc(2026, 10, 15, 8, 0)

    def test_the_end_is_returned_in_utc(self) -> None:
        end = quiet_window_end(OVERNIGHT, "Asia/Kolkata", _utc(2026, 10, 14, 17, 30))
        assert end is not None
        assert end.tzinfo is UTC

    def test_an_unset_timezone_reads_the_window_on_utc(self) -> None:
        assert quiet_window_end(OVERNIGHT, None, _utc(2026, 10, 15, 3, 0)) == _utc(
            2026, 10, 15, 8, 0
        )

    def test_the_end_hour_holds_across_a_fall_back(self) -> None:
        # New York falls back at 02:00 EDT on Nov 1 2026: 08:00 that morning is EST (UTC-5).
        now = _utc(2026, 11, 1, 3, 0)  # 23:00 EDT on Oct 31
        assert quiet_window_end(OVERNIGHT, "America/New_York", now) == _utc(2026, 11, 1, 13, 0)

    def test_the_end_hour_holds_across_a_spring_forward(self) -> None:
        # New York springs forward at 02:00 EST on Mar 8 2026: 08:00 that morning is EDT (UTC-4).
        now = _utc(2026, 3, 8, 4, 0)  # 23:00 EST on Mar 7
        assert quiet_window_end(OVERNIGHT, "America/New_York", now) == _utc(2026, 3, 8, 12, 0)

    def test_an_end_hour_skipped_by_spring_forward_resolves_after_the_gap(self) -> None:
        # 02:00 never happens on Mar 8 2026 in New York; the window ends at 03:00 EDT (07:00 UTC).
        window = QuietHours(start_hour=23, end_hour=2)
        now = _utc(2026, 3, 8, 5, 30)  # 00:30 EST
        assert quiet_window_end(window, "America/New_York", now) == _utc(2026, 3, 8, 7, 0)


class TestHeldUntil:
    def test_routine_messages_wait_out_the_window(self) -> None:
        now = _utc(2026, 10, 15, 2, 0)
        assert held_until(ProactiveMessageClass.ROUTINE, OVERNIGHT, "UTC", now) == _utc(
            2026, 10, 15, 8, 0
        )

    def test_the_hold_is_read_on_the_users_clock(self) -> None:
        # 17:30 UTC is 23:00 in Kolkata: held until 08:00 IST; on a UTC clock, not held.
        now = _utc(2026, 10, 14, 17, 30)
        assert held_until(ProactiveMessageClass.ROUTINE, OVERNIGHT, "Asia/Kolkata", now) == _utc(
            2026, 10, 15, 2, 30
        )

    def test_a_reminder_the_user_timed_is_never_held(self) -> None:
        now = _utc(2026, 10, 15, 2, 0)
        assert held_until(ProactiveMessageClass.USER_TIMED, OVERNIGHT, "UTC", now) is None

    def test_a_reply_to_the_users_own_action_is_never_held(self) -> None:
        now = _utc(2026, 10, 15, 2, 0)
        assert held_until(ProactiveMessageClass.USER_TRIGGERED, OVERNIGHT, "UTC", now) is None

    def test_only_routine_messages_are_held(self) -> None:
        assert set(ProactiveMessageClass) - QUIET_HOURS_EXEMPT == {ProactiveMessageClass.ROUTINE}
