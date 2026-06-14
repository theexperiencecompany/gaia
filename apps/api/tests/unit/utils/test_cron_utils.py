"""Unit tests for cron utilities.

Timezone parsing now lives in ``app.utils.timezone.Timezone`` (covered by
``test_timezone.py``); these tests cover cron validation and the cron-in-timezone
→ UTC scheduling math, which is the load-bearing correctness for reminders and
workflows.
"""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.utils.cron_utils import (
    CronError,
    calculate_next_occurrences,
    get_next_run_time,
    validate_cron_expression,
)
from app.utils.timezone import Timezone

# Frozen instant reused across tests that need a deterministic "now".
FROZEN_NOW = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)


def _patch_now():
    """Patch datetime.now in the cron_utils module to return FROZEN_NOW."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz:
                return FROZEN_NOW.astimezone(tz)
            return FROZEN_NOW

    return patch("app.utils.cron_utils.datetime", FrozenDatetime)


# ---------------------------------------------------------------------------
# CronError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCronError:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(CronError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(CronError, match="test error"):
            raise CronError("test error")

    def test_stores_message(self) -> None:
        assert str(CronError("something went wrong")) == "something went wrong"

    def test_empty_message(self) -> None:
        assert str(CronError()) == ""


# ---------------------------------------------------------------------------
# validate_cron_expression
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateCronExpression:
    @pytest.mark.parametrize(
        "cron_expr",
        [
            "* * * * *",
            "0 8 * * *",
            "*/5 * * * *",
            "0 9 * * 1",
            "0 0 1 1 *",
            "30 14 * * 1-5",
            "0 */2 * * *",
            "0 9 1 * *",
        ],
    )
    def test_valid_expressions_return_true(self, cron_expr: str) -> None:
        assert validate_cron_expression(cron_expr) is True

    @pytest.mark.parametrize(
        "cron_expr",
        ["not a cron", "60 * * * *", "* 25 * * *", "* * 32 * *", "* * * 13 *", "", "0 8 * *"],
    )
    def test_invalid_expressions_return_false(self, cron_expr: str) -> None:
        assert validate_cron_expression(cron_expr) is False

    def test_none_raises_attribute_error(self) -> None:
        # croniter raises AttributeError for non-string inputs, not caught by validate.
        with pytest.raises(AttributeError):
            validate_cron_expression(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_next_run_time — cron interpreted in a Timezone, returned in UTC
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNextRunTime:
    def test_valid_cron_with_base_time_default_utc(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        assert get_next_run_time("0 8 * * *", base_time=base) == datetime(
            2025, 1, 1, 8, 0, 0, tzinfo=UTC
        )

    def test_invalid_cron_raises_cron_error(self) -> None:
        with pytest.raises(CronError, match="Invalid cron expression"):
            get_next_run_time("not valid")

    def test_none_base_time_uses_now(self) -> None:
        with _patch_now():
            result = get_next_run_time("0 12 * * *")
        assert result == datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_naive_datetime_assumed_utc(self) -> None:
        base = datetime(2025, 3, 10, 6, 30, 0)  # naive
        assert get_next_run_time("0 8 * * *", base_time=base) == datetime(
            2025, 3, 10, 8, 0, 0, tzinfo=UTC
        )

    def test_9am_ist_is_0330_utc(self) -> None:
        # The reported bug: "daily at 9 AM" in IST must fire at 03:30 UTC, not 09:00.
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * *", base_time=base, tz=Timezone.parse("Asia/Kolkata"))
        assert result == datetime(2025, 1, 1, 3, 30, 0, tzinfo=UTC)

    def test_iana_and_equivalent_offset_agree(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        by_name = get_next_run_time("0 9 * * *", base_time=base, tz=Timezone.parse("Asia/Kolkata"))
        by_offset = get_next_run_time("0 9 * * *", base_time=base, tz=Timezone.parse("+05:30"))
        assert by_name == by_offset

    def test_utc_timezone_matches_default(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        assert get_next_run_time("0 8 * * *", base_time=base, tz=Timezone.utc()) == datetime(
            2025, 1, 1, 8, 0, 0, tzinfo=UTC
        )

    def test_with_timezone_and_none_base_time(self) -> None:
        with _patch_now():
            result = get_next_run_time(
                "0 8 * * *", base_time=None, tz=Timezone.parse("America/New_York")
            )
        # Frozen 10 AM UTC = 6 AM EDT (-4 in June). Next 8 AM EDT = 12 PM UTC.
        assert result == datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_aware_base_time_in_other_zone(self) -> None:
        base = datetime(2025, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("US/Eastern"))  # 6 AM EST
        result = get_next_run_time("0 8 * * *", base_time=base, tz=Timezone.parse("US/Eastern"))
        # Next 8 AM EST = Jan 1 13:00 UTC (EST -5).
        assert result == datetime(2025, 1, 1, 13, 0, 0, tzinfo=UTC)

    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        # Timezone.parse("Invalid/Zone") -> UTC, so the cron runs in UTC.
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        assert get_next_run_time(
            "0 8 * * *", base_time=base, tz=Timezone.parse("Invalid/Zone")
        ) == datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)

    def test_result_is_always_utc_aware(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 8 * * *", base_time=base)
        assert result.tzinfo is not None and result.utcoffset() == timedelta(0)

    def test_offset_timezone(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        # 7 AM UTC = 12:30 +05:30; next 8 AM +05:30 = Jan 2 02:30 UTC.
        assert get_next_run_time(
            "0 8 * * *", base_time=base, tz=Timezone.parse("+05:30")
        ) == datetime(2025, 1, 2, 2, 30, 0, tzinfo=UTC)

    def test_none_timezone_uses_utc(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        assert get_next_run_time("0 8 * * *", base_time=base, tz=None) == datetime(
            2025, 1, 1, 8, 0, 0, tzinfo=UTC
        )

    def test_aware_base_without_tz_uses_base_zone(self) -> None:
        # Regression: a tz-aware base with NO explicit tz is interpreted in the
        # base's OWN zone (the reminder first-fire path passes a local "now" and
        # no tz), not silently reinterpreted in UTC.
        ist = timezone(timedelta(hours=5, minutes=30))
        base = datetime(2025, 6, 14, 14, 30, 0, tzinfo=ist)  # 14:30 IST
        result = get_next_run_time("0 9 * * *", base_time=base)  # tz omitted
        assert result == datetime(2025, 6, 15, 3, 30, 0, tzinfo=UTC)  # next 9AM IST

    def test_dst_iana_shifts_but_fixed_offset_does_not(self) -> None:
        # THE reason IANA beats a fixed offset. US DST starts 2025-03-09.
        # "0 9 * * *" in America/New_York:
        #   - just before DST (base Mar 7): next fire Mar 8 09:00 EST = 14:00 UTC
        #   - just after  DST (base Mar 9): next fire Mar 10 09:00 EDT = 13:00 UTC
        ny = Timezone.parse("America/New_York")
        before = get_next_run_time(
            "0 9 * * *", base_time=datetime(2025, 3, 7, 20, 0, tzinfo=UTC), tz=ny
        )
        after = get_next_run_time(
            "0 9 * * *", base_time=datetime(2025, 3, 9, 20, 0, tzinfo=UTC), tz=ny
        )
        assert before.hour == 14  # EST
        assert after.hour == 13  # EDT — the wall-clock 9 AM moved an hour in UTC
        # A fixed -05:00 offset can't track DST: it stays 14:00 UTC year-round.
        fixed = Timezone.parse("-05:00")
        fixed_after = get_next_run_time(
            "0 9 * * *", base_time=datetime(2025, 3, 9, 20, 0, tzinfo=UTC), tz=fixed
        )
        assert fixed_after.hour == 14


# ---------------------------------------------------------------------------
# calculate_next_occurrences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateNextOccurrences:
    def test_valid_cron_returns_list(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        result = calculate_next_occurrences("0 8 * * *", count=3, base_time=base)
        assert result == [
            datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 2, 8, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 3, 8, 0, 0, tzinfo=UTC),
        ]

    @pytest.mark.parametrize("count", [0, -5])
    def test_non_positive_count_returns_empty(self, count: int) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=UTC)
        assert calculate_next_occurrences("0 8 * * *", count=count, base_time=base) == []

    def test_invalid_cron_raises_cron_error(self) -> None:
        with pytest.raises(CronError, match="Invalid cron expression"):
            calculate_next_occurrences("bad cron", count=3)

    def test_occurrences_are_chronological(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = calculate_next_occurrences("*/15 * * * *", count=5, base_time=base)
        assert all(result[i] < result[i + 1] for i in range(len(result) - 1))

    def test_none_base_time_uses_now(self) -> None:
        with _patch_now():
            result = calculate_next_occurrences("0 * * * *", count=2)
        assert result == [
            datetime(2025, 6, 15, 11, 0, 0, tzinfo=UTC),
            datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        ]

    def test_all_results_are_utc_aware(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = calculate_next_occurrences("0 */6 * * *", count=4, base_time=base)
        assert all(dt.tzinfo is not None and dt.utcoffset() == timedelta(0) for dt in result)

    def test_weekly_cron_occurrences(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)  # Wednesday
        result = calculate_next_occurrences("0 9 * * 1", count=2, base_time=base)  # Mondays
        assert result == [
            datetime(2025, 1, 6, 9, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 13, 9, 0, 0, tzinfo=UTC),
        ]
