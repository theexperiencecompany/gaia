"""Unit tests for cron utilities."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytz
import pytest

from app.utils.cron_utils import (
    COMMON_CRON_EXPRESSIONS,
    CronError,
    calculate_next_occurrences,
    get_next_run_time,
    get_previous_run_time,
    is_time_in_future,
    parse_timezone,
    validate_cron_expression,
)

# Frozen instant reused across tests that need a deterministic "now".
FROZEN_NOW = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


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
        err = CronError("something went wrong")
        assert str(err) == "something went wrong"

    def test_empty_message(self) -> None:
        err = CronError()
        assert str(err) == ""


# ---------------------------------------------------------------------------
# parse_timezone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseTimezone:
    def test_none_returns_utc(self) -> None:
        result = parse_timezone(None)  # type: ignore[arg-type]
        assert result is timezone.utc

    def test_empty_string_returns_utc(self) -> None:
        result = parse_timezone("")
        assert result is timezone.utc

    def test_utc_string_returns_utc(self) -> None:
        result = parse_timezone("UTC")
        assert result is timezone.utc

    @pytest.mark.parametrize(
        "offset_str, expected_hours, expected_minutes",
        [
            ("+05:30", 5, 30),
            ("+00:00", 0, 0),
            ("+12:00", 12, 0),
            ("+09:30", 9, 30),
        ],
    )
    def test_positive_offset(
        self, offset_str: str, expected_hours: int, expected_minutes: int
    ) -> None:
        result = parse_timezone(offset_str)
        expected = timezone(timedelta(hours=expected_hours, minutes=expected_minutes))
        assert result == expected

    @pytest.mark.parametrize(
        "offset_str, expected_hours, expected_minutes",
        [
            ("-08:00", 8, 0),
            ("-05:30", 5, 30),
            ("-12:00", 12, 0),
            ("-00:00", 0, 0),
        ],
    )
    def test_negative_offset(
        self, offset_str: str, expected_hours: int, expected_minutes: int
    ) -> None:
        result = parse_timezone(offset_str)
        expected = timezone(-timedelta(hours=expected_hours, minutes=expected_minutes))
        assert result == expected

    @pytest.mark.parametrize(
        "iana_name",
        [
            "America/New_York",
            "Asia/Kolkata",
            "Europe/London",
            "Asia/Tokyo",
            "US/Pacific",
        ],
    )
    def test_valid_iana_timezone(self, iana_name: str) -> None:
        result = parse_timezone(iana_name)
        expected = pytz.timezone(iana_name)
        assert result == expected

    @pytest.mark.parametrize(
        "invalid_tz",
        [
            "Invalid/Timezone",
            "Not_A_Zone",
            "Foo/Bar/Baz",
            "CEST",
        ],
    )
    def test_invalid_timezone_raises_value_error(self, invalid_tz: str) -> None:
        with pytest.raises(ValueError, match="Unknown timezone format"):
            parse_timezone(invalid_tz)

    def test_offset_boundary_values(self) -> None:
        result = parse_timezone("+14:00")
        assert result == timezone(timedelta(hours=14))

    def test_offset_string_without_colon_not_matched(self) -> None:
        # "+0530" doesn't match the offset regex, falls through to IANA lookup
        with pytest.raises(ValueError, match="Unknown timezone format"):
            parse_timezone("+0530")


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
        [
            "not a cron",
            "60 * * * *",
            "* 25 * * *",
            "* * 32 * *",
            "* * * 13 *",
            "* * * * 8",
            "",
            "0 8 * *",  # too few fields
        ],
    )
    def test_invalid_expressions_return_false(self, cron_expr: str) -> None:
        assert validate_cron_expression(cron_expr) is False

    def test_none_raises_attribute_error(self) -> None:
        # croniter raises AttributeError for non-string inputs, which is not
        # caught by validate_cron_expression (only ValueError/TypeError are caught)
        with pytest.raises(AttributeError):
            validate_cron_expression(None)  # type: ignore[arg-type]

    def test_integer_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            validate_cron_expression(123)  # type: ignore[arg-type]

    def test_list_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            validate_cron_expression([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_next_run_time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNextRunTime:
    def test_valid_cron_with_base_time(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base)
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_invalid_cron_raises_cron_error(self) -> None:
        with pytest.raises(CronError, match="Invalid cron expression"):
            get_next_run_time("not valid")

    def test_none_base_time_uses_now(self) -> None:
        with _patch_now():
            result = get_next_run_time("0 12 * * *")
        expected = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_naive_datetime_assumed_utc(self) -> None:
        base = datetime(2025, 3, 10, 6, 30, 0)  # naive
        result = get_next_run_time("0 8 * * *", base_time=base)
        expected = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_timezone_converts_to_utc(self) -> None:
        # 7 AM UTC -> in Asia/Kolkata that's 12:30 PM IST
        # Next "0 8 * * *" in Kolkata (8 AM IST) would be next day
        # 8 AM IST = 2:30 AM UTC
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time(
            "0 8 * * *", base_time=base, user_timezone="Asia/Kolkata"
        )
        expected = datetime(2025, 1, 2, 2, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_utc_timezone_string(self) -> None:
        # When user_timezone is "UTC", should fall through to default UTC path
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base, user_timezone="UTC")
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_timezone_and_none_base_time(self) -> None:
        with _patch_now():
            result = get_next_run_time(
                "0 8 * * *", base_time=None, user_timezone="America/New_York"
            )
        # Frozen at 10 AM UTC = 6 AM ET (EDT, -4). Next 8 AM ET = 12 PM UTC
        expected = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_timezone_and_naive_base_time(self) -> None:
        # Naive base_time should be treated as UTC then converted to user tz
        base = datetime(2025, 1, 1, 7, 0, 0)  # naive
        result = get_next_run_time(
            "0 8 * * *", base_time=base, user_timezone="Asia/Kolkata"
        )
        # Naive assumed UTC -> 12:30 PM IST. Next 8 AM IST = Jan 2 2:30 AM UTC
        expected = datetime(2025, 1, 2, 2, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_timezone_and_aware_base_time(self) -> None:
        eastern = pytz.timezone("US/Eastern")
        base = eastern.localize(datetime(2025, 1, 1, 6, 0, 0))  # 6 AM ET
        result = get_next_run_time(
            "0 8 * * *", base_time=base, user_timezone="US/Eastern"
        )
        # Next 8 AM ET = Jan 1 8 AM ET = Jan 1 1 PM UTC (EST offset -5)
        expected = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_timezone_parse_failure_falls_back_to_utc(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time(
            "0 8 * * *", base_time=base, user_timezone="Invalid/Fake_Zone"
        )
        # parse_timezone raises ValueError, caught by the broad except in
        # get_next_run_time, falls back to UTC calculation
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_result_is_always_utc_aware(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base)
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_every_minute_cron(self) -> None:
        base = datetime(2025, 1, 1, 12, 30, 15, tzinfo=timezone.utc)
        result = get_next_run_time("* * * * *", base_time=base)
        expected = datetime(2025, 1, 1, 12, 31, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_with_offset_timezone(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base, user_timezone="+05:30")
        # 7 AM UTC = 12:30 PM +05:30, next 8 AM +05:30 = Jan 2 2:30 AM UTC
        expected = datetime(2025, 1, 2, 2, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_none_timezone_uses_utc_path(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base, user_timezone=None)
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_empty_timezone_uses_utc_path(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = get_next_run_time("0 8 * * *", base_time=base, user_timezone="")
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected


# ---------------------------------------------------------------------------
# get_previous_run_time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPreviousRunTime:
    def test_valid_cron_with_base_time(self) -> None:
        base = datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        result = get_previous_run_time("0 8 * * *", base_time=base)
        expected = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_invalid_cron_raises_cron_error(self) -> None:
        with pytest.raises(CronError, match="Invalid cron expression"):
            get_previous_run_time("invalid")

    def test_none_base_time_uses_now(self) -> None:
        with _patch_now():
            result = get_previous_run_time("0 * * * *")
        # Previous occurrence of "every hour at :00" when now is 10:00 is 09:00
        expected = datetime(2025, 6, 15, 9, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_naive_datetime_assumed_utc(self) -> None:
        base = datetime(2025, 3, 10, 9, 30, 0)  # naive
        result = get_previous_run_time("0 8 * * *", base_time=base)
        expected = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_result_is_utc_aware(self) -> None:
        base = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = get_previous_run_time("0 8 * * *", base_time=base)
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_previous_run_crosses_day_boundary(self) -> None:
        base = datetime(2025, 1, 2, 1, 0, 0, tzinfo=timezone.utc)
        result = get_previous_run_time("0 22 * * *", base_time=base)
        expected = datetime(2025, 1, 1, 22, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_every_minute_cron(self) -> None:
        base = datetime(2025, 1, 1, 12, 30, 45, tzinfo=timezone.utc)
        result = get_previous_run_time("* * * * *", base_time=base)
        expected = datetime(2025, 1, 1, 12, 30, 0, tzinfo=timezone.utc)
        assert result == expected


# ---------------------------------------------------------------------------
# calculate_next_occurrences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateNextOccurrences:
    def test_valid_cron_returns_list(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("0 8 * * *", count=3, base_time=base)
        assert len(result) == 3
        assert result[0] == datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert result[1] == datetime(2025, 1, 2, 8, 0, 0, tzinfo=timezone.utc)
        assert result[2] == datetime(2025, 1, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_count_zero_returns_empty_list(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("0 8 * * *", count=0, base_time=base)
        assert result == []

    def test_negative_count_returns_empty_list(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("0 8 * * *", count=-5, base_time=base)
        assert result == []

    def test_invalid_cron_raises_cron_error(self) -> None:
        with pytest.raises(CronError, match="Invalid cron expression"):
            calculate_next_occurrences("bad cron", count=3)

    def test_count_one_returns_single_item(self) -> None:
        base = datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("0 8 * * *", count=1, base_time=base)
        assert len(result) == 1
        assert result[0] == datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_occurrences_are_in_chronological_order(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("*/15 * * * *", count=5, base_time=base)
        for i in range(len(result) - 1):
            assert result[i] < result[i + 1]

    def test_none_base_time_uses_now(self) -> None:
        with _patch_now():
            result = calculate_next_occurrences("0 * * * *", count=2)
        assert result[0] == datetime(2025, 6, 15, 11, 0, 0, tzinfo=timezone.utc)
        assert result[1] == datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_naive_base_time_assumed_utc(self) -> None:
        base = datetime(2025, 3, 10, 7, 0, 0)  # naive
        result = calculate_next_occurrences("0 8 * * *", count=1, base_time=base)
        assert result[0] == datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)

    def test_all_results_are_utc_aware(self) -> None:
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = calculate_next_occurrences("0 */6 * * *", count=4, base_time=base)
        for dt in result:
            assert dt.tzinfo is not None
            assert dt.utcoffset() == timedelta(0)

    def test_weekly_cron_occurrences(self) -> None:
        # Wednesday Jan 1 2025
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Every Monday at 9 AM
        result = calculate_next_occurrences("0 9 * * 1", count=2, base_time=base)
        # First Monday after Jan 1 is Jan 6
        assert result[0] == datetime(2025, 1, 6, 9, 0, 0, tzinfo=timezone.utc)
        assert result[1] == datetime(2025, 1, 13, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# is_time_in_future
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsTimeInFuture:
    def test_future_time_returns_true(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        assert is_time_in_future(target, reference) is True

    def test_past_time_returns_false(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        assert is_time_in_future(target, reference) is False

    def test_equal_time_returns_false(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert is_time_in_future(target, reference) is False

    def test_none_reference_future_target(self) -> None:
        with _patch_now():
            future = FROZEN_NOW + timedelta(hours=1)
            result = is_time_in_future(future)
        assert result is True

    def test_none_reference_past_target(self) -> None:
        with _patch_now():
            past = FROZEN_NOW - timedelta(hours=1)
            result = is_time_in_future(past)
        assert result is False

    def test_naive_target_assumed_utc(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 13, 0, 0)  # naive
        assert is_time_in_future(target, reference) is True

    def test_naive_reference_assumed_utc(self) -> None:
        target = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        reference = datetime(2025, 1, 1, 12, 0, 0)  # naive
        assert is_time_in_future(target, reference) is True

    def test_both_naive_datetimes(self) -> None:
        target = datetime(2025, 1, 1, 13, 0, 0)  # naive
        reference = datetime(2025, 1, 1, 12, 0, 0)  # naive
        assert is_time_in_future(target, reference) is True

    def test_both_naive_datetimes_past(self) -> None:
        target = datetime(2025, 1, 1, 11, 0, 0)  # naive
        reference = datetime(2025, 1, 1, 12, 0, 0)  # naive
        assert is_time_in_future(target, reference) is False

    def test_microsecond_difference_future(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 12, 0, 0, 1, tzinfo=timezone.utc)
        assert is_time_in_future(target, reference) is True

    def test_microsecond_difference_past(self) -> None:
        reference = datetime(2025, 1, 1, 12, 0, 0, 1, tzinfo=timezone.utc)
        target = datetime(2025, 1, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
        assert is_time_in_future(target, reference) is False

    def test_different_timezones_compared_correctly(self) -> None:
        # 1 PM UTC = 6:30 PM IST, which is after 5 PM IST (11:30 AM UTC)
        ist = timezone(timedelta(hours=5, minutes=30))
        target = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        reference = datetime(2025, 1, 1, 17, 0, 0, tzinfo=ist)  # 11:30 AM UTC
        assert is_time_in_future(target, reference) is True


# ---------------------------------------------------------------------------
# COMMON_CRON_EXPRESSIONS
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommonCronExpressions:
    def test_all_expressions_are_valid(self) -> None:
        for name, expr in COMMON_CRON_EXPRESSIONS.items():
            assert validate_cron_expression(expr) is True, (
                f"Expression '{name}': '{expr}' should be valid"
            )

    def test_expected_keys_exist(self) -> None:
        expected_keys = {
            "every_minute",
            "every_5_minutes",
            "every_15_minutes",
            "every_30_minutes",
            "hourly",
            "daily_8am",
            "daily_noon",
            "daily_6pm",
            "weekly_monday_9am",
            "monthly_first_day",
            "yearly_jan_1st",
        }
        assert set(COMMON_CRON_EXPRESSIONS.keys()) == expected_keys

    def test_every_minute_value(self) -> None:
        assert COMMON_CRON_EXPRESSIONS["every_minute"] == "* * * * *"

    def test_daily_8am_value(self) -> None:
        assert COMMON_CRON_EXPRESSIONS["daily_8am"] == "0 8 * * *"
