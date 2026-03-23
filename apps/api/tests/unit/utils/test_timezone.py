"""Unit tests for timezone utilities."""

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

import pytz
import pytest

from app.utils.timezone import (
    TIMEZONE_KOLKATA,
    TIMEZONE_LONDON,
    TIMEZONE_NEW_YORK,
    TIMEZONE_TOKYO,
    TIMEZONE_UTC,
    add_timezone_info,
    convert_datetime_to_timezone,
    get_timezone_from_datetime,
    parse_timezone,
    replace_timezone_info,
    set_timezone_preserving_time,
)


class _StubTzInfo(tzinfo):
    """A minimal tzinfo subclass for testing edge cases where tzname returns
    None or empty string."""

    def __init__(self, name: Optional[str]) -> None:
        self._name = name

    def tzname(self, dt: Optional[datetime]) -> Optional[str]:
        return self._name

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        return timedelta(0)

    def dst(self, dt: Optional[datetime]) -> timedelta:
        return timedelta(0)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModuleConstants:
    def test_timezone_utc_is_builtin_utc(self):
        assert TIMEZONE_UTC is timezone.utc

    def test_timezone_kolkata_value(self):
        assert TIMEZONE_KOLKATA == "Asia/Kolkata"

    def test_timezone_new_york_value(self):
        assert TIMEZONE_NEW_YORK == "America/New_York"

    def test_timezone_london_value(self):
        assert TIMEZONE_LONDON == "Europe/London"

    def test_timezone_tokyo_value(self):
        assert TIMEZONE_TOKYO == "Asia/Tokyo"


# ---------------------------------------------------------------------------
# parse_timezone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseTimezone:
    def test_utc_string_returns_builtin_utc(self):
        result = parse_timezone("UTC")
        assert result is timezone.utc

    @pytest.mark.parametrize("utc_variant", ["UTC", "utc", "Utc", "uTc"])
    def test_utc_string_case_insensitive(self, utc_variant: str):
        result = parse_timezone(utc_variant)
        assert result is timezone.utc

    @pytest.mark.parametrize(
        "tz_name",
        [
            "America/New_York",
            "Asia/Kolkata",
            "Europe/London",
            "Asia/Tokyo",
            "US/Eastern",
            "US/Pacific",
        ],
    )
    def test_valid_pytz_timezone_strings(self, tz_name: str):
        result = parse_timezone(tz_name)
        assert result == pytz.timezone(tz_name)

    def test_invalid_timezone_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown timezone string"):
            parse_timezone("Not/A_Timezone")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown timezone string"):
            parse_timezone("")

    def test_builtin_timezone_object_returned_as_is(self):
        tz = timezone(timedelta(hours=5, minutes=30))
        result = parse_timezone(tz)
        assert result is tz

    def test_builtin_utc_object_returned_as_is(self):
        result = parse_timezone(timezone.utc)
        assert result is timezone.utc

    def test_non_string_non_timezone_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid timezone type"):
            parse_timezone(12345)  # type: ignore[arg-type]

    def test_none_input_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid timezone type"):
            parse_timezone(None)  # type: ignore[arg-type]

    def test_pytz_timezone_object_raises_value_error(self):
        """pytz.BaseTzInfo is not an instance of datetime.timezone, so it should
        go through the string path internally. Passing a pytz object directly
        should hit the else branch and raise."""
        tz = pytz.timezone("Asia/Kolkata")
        # pytz.BaseTzInfo is not an instance of datetime.timezone (builtin_timezone)
        # so it falls into the else branch
        with pytest.raises(ValueError, match="Invalid timezone type"):
            parse_timezone(tz)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# replace_timezone_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReplaceTimezoneInfo:
    def test_string_datetime_with_new_timezone_string(self):
        result = replace_timezone_info("2025-06-18T19:00:00", new_timezone="UTC")
        assert result == datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        assert result.hour == 19

    def test_datetime_object_with_new_timezone_string(self):
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        result = replace_timezone_info(dt, new_timezone="Asia/Kolkata")
        # Time should stay 19:00, only timezone changes
        assert result.hour == 19
        assert result.minute == 0
        assert result.tzinfo is not None

    def test_preserves_time_values_not_converts(self):
        dt = datetime(2025, 6, 18, 7, 0, 0, tzinfo=timezone.utc)
        kolkata_tz = pytz.timezone("Asia/Kolkata")
        result = replace_timezone_info(dt, new_timezone="Asia/Kolkata")
        # Time should NOT change from 7:00 to 12:30 -- it stays 7:00
        assert result.hour == 7
        assert result.minute == 0
        assert result.tzinfo == kolkata_tz

    def test_string_datetime_with_timezone_source_datetime(self):
        source = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = replace_timezone_info("2025-06-18T19:00:00", timezone_source=source)
        assert result.tzinfo is timezone.utc
        assert result.hour == 19

    def test_string_datetime_with_timezone_source_string(self):
        result = replace_timezone_info(
            "2025-06-18T19:00:00",
            timezone_source="2025-01-01T00:00:00+05:30",
        )
        assert result.tzinfo is not None
        assert result.hour == 19

    def test_new_timezone_takes_precedence_over_timezone_source(self):
        source = datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        result = replace_timezone_info(
            datetime(2025, 6, 18, 19, 0, 0),
            new_timezone="UTC",
            timezone_source=source,
        )
        assert result.tzinfo is timezone.utc

    def test_neither_param_raises_value_error(self):
        with pytest.raises(
            ValueError,
            match="Either 'new_timezone' or 'timezone_source' must be provided",
        ):
            replace_timezone_info(datetime(2025, 6, 18, 19, 0, 0))

    def test_timezone_source_naive_datetime_raises_value_error(self):
        """When timezone_source is a naive datetime, its tzinfo is None,
        which should trigger the 'Could not determine' error."""
        with pytest.raises(
            ValueError,
            match="Could not determine target timezone",
        ):
            replace_timezone_info(
                datetime(2025, 6, 18, 19, 0, 0),
                timezone_source=datetime(2025, 1, 1),
            )

    def test_invalid_new_timezone_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown timezone string"):
            replace_timezone_info(
                datetime(2025, 6, 18, 19, 0, 0),
                new_timezone="Invalid/Zone",
            )

    def test_builtin_timezone_object_as_new_timezone(self):
        tz = timezone(timedelta(hours=-5))
        dt = datetime(2025, 6, 18, 19, 0, 0)
        result = replace_timezone_info(dt, new_timezone=tz)
        assert result.tzinfo is tz
        assert result.hour == 19

    def test_string_iso_with_existing_tz_gets_replaced(self):
        # String already has timezone info (+00:00), which gets replaced
        result = replace_timezone_info(
            "2025-06-18T19:00:00+00:00",
            new_timezone="America/New_York",
        )
        assert result.hour == 19
        assert result.tzinfo == pytz.timezone("America/New_York")


# ---------------------------------------------------------------------------
# convert_datetime_to_timezone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConvertDatetimeToTimezone:
    def test_utc_to_kolkata_converts_time(self):
        utc_dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        result = convert_datetime_to_timezone(utc_dt, "Asia/Kolkata")
        # UTC+5:30 => 19:00 + 5:30 = 00:30 next day
        assert result.hour == 0
        assert result.minute == 30
        assert result.day == 19

    def test_kolkata_to_utc_converts_time(self):
        kolkata_tz = pytz.timezone("Asia/Kolkata")
        kolkata_dt = kolkata_tz.localize(datetime(2025, 6, 19, 0, 30, 0))
        result = convert_datetime_to_timezone(kolkata_dt, "UTC")
        assert result.hour == 19
        assert result.minute == 0
        assert result.day == 18

    def test_string_input_with_timezone(self):
        result = convert_datetime_to_timezone(
            "2025-06-18T19:00:00+00:00",
            "Asia/Kolkata",
        )
        assert result.hour == 0
        assert result.minute == 30

    def test_naive_datetime_raises_value_error(self):
        naive_dt = datetime(2025, 6, 18, 19, 0, 0)
        with pytest.raises(
            ValueError,
            match="Source datetime must have timezone information",
        ):
            convert_datetime_to_timezone(naive_dt, "UTC")

    def test_naive_string_raises_value_error(self):
        with pytest.raises(
            ValueError,
            match="Source datetime must have timezone information",
        ):
            convert_datetime_to_timezone("2025-06-18T19:00:00", "UTC")

    def test_invalid_target_timezone_raises_value_error(self):
        utc_dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Unknown timezone string"):
            convert_datetime_to_timezone(utc_dt, "Fake/Zone")

    def test_same_timezone_no_change(self):
        utc_dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        result = convert_datetime_to_timezone(utc_dt, "UTC")
        assert result.hour == 19
        assert result.minute == 0

    def test_builtin_timezone_object_as_target(self):
        utc_dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        eastern = timezone(timedelta(hours=-5))
        result = convert_datetime_to_timezone(utc_dt, eastern)
        assert result.hour == 14
        assert result.minute == 0

    @pytest.mark.parametrize(
        ("source_tz", "target_tz", "source_hour", "expected_hour"),
        [
            ("UTC", "US/Eastern", 20, 16),  # UTC-4 (EDT)
            ("UTC", "US/Pacific", 20, 13),  # UTC-7 (PDT)
            ("UTC", "Asia/Tokyo", 15, 0),  # UTC+9 => next day midnight
        ],
    )
    def test_various_timezone_conversions(
        self,
        source_tz: str,
        target_tz: str,
        source_hour: int,
        expected_hour: int,
    ):
        # Use a summer date to get DST offsets
        src_tz = pytz.timezone(source_tz)
        dt = src_tz.localize(datetime(2025, 6, 18, source_hour, 0, 0))
        result = convert_datetime_to_timezone(dt, target_tz)
        assert result.hour == expected_hour


# ---------------------------------------------------------------------------
# set_timezone_preserving_time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetTimezonePreservingTime:
    def test_delegates_to_replace_timezone_info(self):
        dt = datetime(2025, 6, 18, 19, 0, 0)
        result = set_timezone_preserving_time(dt, "Asia/Kolkata")
        expected = replace_timezone_info(dt, new_timezone="Asia/Kolkata")
        assert result == expected

    def test_string_input(self):
        result = set_timezone_preserving_time("2025-06-18T19:00:00", "UTC")
        assert result.hour == 19
        assert result.tzinfo is timezone.utc

    def test_preserves_time_values(self):
        dt = datetime(2025, 3, 15, 14, 30, 45)
        result = set_timezone_preserving_time(dt, "America/New_York")
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 45

    def test_invalid_timezone_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown timezone string"):
            set_timezone_preserving_time(datetime(2025, 1, 1), "Bogus/Zone")


# ---------------------------------------------------------------------------
# add_timezone_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddTimezoneInfo:
    def test_naive_datetime_gets_timezone_added(self):
        dt = datetime(2025, 6, 18, 19, 0, 0)
        result = add_timezone_info(dt, "UTC")
        assert result.tzinfo is timezone.utc
        assert result.hour == 19

    def test_aware_datetime_is_returned_unchanged(self):
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        result = add_timezone_info(dt, "Asia/Kolkata")
        # Should return original datetime since it already has tzinfo
        assert result is dt
        assert result.tzinfo is timezone.utc

    def test_string_naive_gets_timezone_added(self):
        result = add_timezone_info("2025-06-18T19:00:00", "Asia/Kolkata")
        assert result.tzinfo is not None
        assert result.hour == 19

    def test_string_aware_is_returned_unchanged(self):
        result = add_timezone_info("2025-06-18T19:00:00+00:00", "Asia/Kolkata")
        # Parsing the string gives an aware datetime, so it should be returned as-is
        assert result.tzinfo is not None
        # The timezone should be the original UTC, not Kolkata
        assert result.utcoffset() == timedelta(0)

    def test_preserves_time_when_adding_timezone(self):
        dt = datetime(2025, 12, 25, 8, 15, 30, 123456)
        result = add_timezone_info(dt, "Europe/London")
        assert result.hour == 8
        assert result.minute == 15
        assert result.second == 30
        assert result.microsecond == 123456

    def test_invalid_timezone_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown timezone string"):
            add_timezone_info(datetime(2025, 1, 1), "Not/Real")

    @pytest.mark.parametrize(
        "tz_name",
        ["UTC", "America/New_York", "Asia/Tokyo", "Europe/London"],
    )
    def test_various_timezones_on_naive_datetime(self, tz_name: str):
        dt = datetime(2025, 6, 18, 12, 0, 0)
        result = add_timezone_info(dt, tz_name)
        assert result.tzinfo is not None
        assert result.hour == 12


# ---------------------------------------------------------------------------
# get_timezone_from_datetime
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTimezoneFromDatetime:
    def test_utc_datetime_returns_utc(self):
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)
        result = get_timezone_from_datetime(dt)
        assert result == "UTC"

    def test_pytz_aware_datetime(self):
        tz = pytz.timezone("Asia/Kolkata")
        dt = tz.localize(datetime(2025, 6, 18, 19, 0, 0))
        result = get_timezone_from_datetime(dt)
        assert result == "IST"

    def test_string_with_timezone(self):
        result = get_timezone_from_datetime("2025-06-18T19:00:00+00:00")
        assert result == "UTC"

    def test_naive_datetime_raises_value_error(self):
        dt = datetime(2025, 6, 18, 19, 0, 0)
        with pytest.raises(
            ValueError,
            match="Datetime must have timezone information",
        ):
            get_timezone_from_datetime(dt)

    def test_naive_string_raises_value_error(self):
        with pytest.raises(
            ValueError,
            match="Datetime must have timezone information",
        ):
            get_timezone_from_datetime("2025-06-18T19:00:00")

    def test_fixed_offset_timezone(self):
        tz = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=tz)
        result = get_timezone_from_datetime(dt)
        assert result == "UTC+05:30"

    def test_none_tzname_raises_value_error(self):
        """When tzinfo.tzname() returns None, should raise ValueError."""
        stub_tz = _StubTzInfo(name=None)
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=stub_tz)
        with pytest.raises(
            ValueError,
            match="Could not determine timezone name",
        ):
            get_timezone_from_datetime(dt)

    def test_empty_string_tzname_raises_value_error(self):
        """When tzinfo.tzname() returns empty string, should raise ValueError."""
        stub_tz = _StubTzInfo(name="")
        dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=stub_tz)
        with pytest.raises(
            ValueError,
            match="Could not determine timezone name",
        ):
            get_timezone_from_datetime(dt)

    @pytest.mark.parametrize(
        ("tz_name", "expected_prefix"),
        [
            ("America/New_York", "E"),  # EDT or EST
            ("Europe/London", ""),  # GMT or BST
            ("Asia/Tokyo", "JST"),
        ],
    )
    def test_various_timezone_names(self, tz_name: str, expected_prefix: str):
        tz = pytz.timezone(tz_name)
        dt = tz.localize(datetime(2025, 6, 18, 12, 0, 0))
        result = get_timezone_from_datetime(dt)
        assert isinstance(result, str)
        assert len(result) > 0
        if expected_prefix:
            assert result.startswith(expected_prefix)
