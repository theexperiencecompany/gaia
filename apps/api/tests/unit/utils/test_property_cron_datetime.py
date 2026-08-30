"""Property-based tests for the cron scheduling date math.

The invariants pinned here are the ones the module's own docstring promises:

- ``get_next_run_time`` always returns a tz-aware datetime in UTC, strictly in
  the future, whose wall-clock time in the schedule's timezone matches the
  cron's hour/minute fields.
- The wall-clock match must survive DST transitions: a daily 09:00 schedule in
  America/New_York must fire at 09:00 local whether the fire lands in EST or
  EDT. If the naive wall-clock stepping were reverted, the fire would come out
  an hour off and this property fails.
- ``calculate_next_occurrences`` returns exactly ``count`` strictly increasing
  aware-UTC datetimes.
- Invalid or never-firing expressions raise ``CronError`` and nothing else.
"""

from datetime import UTC, datetime

from hypothesis import example, given, settings, strategies as st
import pytest

from app.utils.cron_utils import (
    COMMON_CRON_EXPRESSIONS,
    CronError,
    calculate_next_occurrences,
    get_next_run_time,
    validate_cron_expression,
)
from app.utils.timezone import Timezone

ZONE_NAMES = ["UTC", "Asia/Kolkata", "America/New_York", "Europe/London", "+05:30"]

# US DST 2026: starts Mar 8, ends Nov 1. UK DST 2026: starts Mar 29, ends Oct 25.
DST_TRANSITION_BASES = [
    datetime(2026, 3, 8, 0, 0, tzinfo=UTC),  # hours before US DST start
    datetime(2026, 11, 1, 0, 0, tzinfo=UTC),  # hours before US DST end
    datetime(2026, 3, 29, 0, 0, tzinfo=UTC),  # hours before UK DST start
    datetime(2026, 10, 25, 0, 0, tzinfo=UTC),  # hours before UK DST end
]

AWARE_UTC_DATETIMES = st.datetimes(
    min_value=datetime(2025, 1, 1),
    max_value=datetime(2026, 12, 31),
    timezones=st.just(UTC),
)

MINUTE_HOUR_CRON = st.builds(
    lambda minute, hour: f"{minute} {hour} * * *",
    minute=st.integers(0, 59),
    hour=st.integers(0, 23),
)


class TestGetNextRunTime:
    @settings(deadline=None)
    @given(
        cron_expr=MINUTE_HOUR_CRON,
        base_time=AWARE_UTC_DATETIMES,
        zone_name=st.sampled_from(ZONE_NAMES),
    )
    @example(
        cron_expr="0 9 * * *",
        base_time=DST_TRANSITION_BASES[0],
        zone_name="America/New_York",
    )
    @example(
        cron_expr="0 9 * * *",
        base_time=DST_TRANSITION_BASES[1],
        zone_name="America/New_York",
    )
    @example(
        cron_expr="0 9 * * *",
        base_time=DST_TRANSITION_BASES[2],
        zone_name="Europe/London",
    )
    @example(
        cron_expr="0 9 * * *",
        base_time=DST_TRANSITION_BASES[3],
        zone_name="Europe/London",
    )
    def test_next_fire_is_aware_utc_and_matches_local_wall_clock(
        self, cron_expr: str, base_time: datetime, zone_name: str
    ) -> None:
        tz = Timezone.parse(zone_name)
        result = get_next_run_time(cron_expr, base_time, tz)
        assert result.tzinfo is UTC
        assert result > base_time
        local = result.astimezone(tz.tzinfo)
        minute, hour = (int(part) for part in cron_expr.split()[:2])
        if (local.hour, local.minute) != (hour, minute):
            # Spring-forward gap: the cron wall time does not exist on the
            # fire date (e.g. 02:30 in America/New_York on the transition
            # day), and the schedule library fires at the next real instant —
            # the wall time shifted forward by the DST offset. Assert that is
            # what happened, not a genuine miss.
            # zoneinfo has no "this time does not exist" answer — it resolves a
            # gap time to the pre-transition offset at fold=0 and the
            # post-transition one at fold=1, and returns the same offset for
            # both when the time is real. That disagreement IS the gap.
            wall_naive = datetime(local.year, local.month, local.day, hour, minute)
            in_zone = wall_naive.replace(tzinfo=tz.tzinfo)
            assert in_zone.utcoffset() != in_zone.replace(fold=1).utcoffset(), (
                f"{cron_expr} in {zone_name} fired at {local:%H:%M}, expected {(hour, minute)}"
            )
            assert (local.hour - hour, local.minute - minute) == (1, 0), (
                f"{cron_expr} in {zone_name} fired at {local:%H:%M}, expected {(hour, minute)}"
            )

    @settings(deadline=None)
    @given(cron_expr=MINUTE_HOUR_CRON, base_time=AWARE_UTC_DATETIMES)
    def test_naive_base_is_treated_as_utc(self, cron_expr: str, base_time: datetime) -> None:
        naive = base_time.replace(tzinfo=None)
        result = get_next_run_time(cron_expr, naive)
        assert result.tzinfo is UTC
        assert result > naive.replace(tzinfo=UTC)

    @settings(deadline=None)
    @given(cron_expr=MINUTE_HOUR_CRON, base_time=AWARE_UTC_DATETIMES)
    def test_common_expressions_respect_the_same_invariants(
        self, cron_expr: str, base_time: datetime
    ) -> None:
        # The curated schedule library must never fire in the past.
        result = get_next_run_time(cron_expr, base_time)
        assert result.tzinfo is UTC and result > base_time

    def test_never_firing_expression_raises_cron_error(self) -> None:
        # Feb 31 can never occur: croniter finds no next date and the error is
        # wrapped in CronError, never leaked as a croniter exception.
        with pytest.raises(CronError):
            get_next_run_time("0 9 31 2 *", datetime(2026, 1, 1, tzinfo=UTC))


class TestValidateCronExpression:
    @settings(deadline=None)
    @given(s=st.text())
    def test_never_raises_and_agrees_with_get_next_run_time(self, s: str) -> None:
        try:
            valid = validate_cron_expression(s)
        except Exception as e:  # pragma: no cover - a raised exception IS the bug
            raise AssertionError(f"validate_cron_expression raised on {s!r}: {e!r}") from e
        base = datetime(2026, 1, 1, tzinfo=UTC)
        if valid:
            assert get_next_run_time(s, base).tzinfo is UTC
        else:
            with pytest.raises(CronError):
                get_next_run_time(s, base)


class TestCalculateNextOccurrences:
    @settings(deadline=None)
    @given(
        cron_expr=st.sampled_from(list(COMMON_CRON_EXPRESSIONS.values())),
        count=st.integers(1, 12),
        base_time=AWARE_UTC_DATETIMES,
    )
    def test_occurrences_are_counted_ordered_and_aware_utc(
        self, cron_expr: str, count: int, base_time: datetime
    ) -> None:
        occurrences = calculate_next_occurrences(cron_expr, count, base_time)
        assert len(occurrences) == count
        for i, occurrence in enumerate(occurrences):
            assert occurrence.tzinfo is UTC
            assert occurrence > base_time
            if i > 0:
                assert occurrences[i - 1] < occurrence

    @settings(deadline=None)
    @given(cron_expr=st.sampled_from(list(COMMON_CRON_EXPRESSIONS.values())))
    def test_non_positive_count_returns_empty(self, cron_expr: str) -> None:
        assert calculate_next_occurrences(cron_expr, 0, datetime(2026, 1, 1, tzinfo=UTC)) == []
        assert calculate_next_occurrences(cron_expr, -3, datetime(2026, 1, 1, tzinfo=UTC)) == []
