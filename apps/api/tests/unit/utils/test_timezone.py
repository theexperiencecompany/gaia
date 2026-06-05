"""Unit tests for timezone utilities."""

from datetime import UTC, timedelta, timezone

import pytest
import pytz

from app.utils.timezone import (
    TIMEZONE_KOLKATA,
    TIMEZONE_LONDON,
    TIMEZONE_NEW_YORK,
    TIMEZONE_TOKYO,
    TIMEZONE_UTC,
    parse_timezone,
)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModuleConstants:
    def test_timezone_utc_is_builtin_utc(self):
        assert TIMEZONE_UTC is UTC

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
        assert result is UTC

    @pytest.mark.parametrize("utc_variant", ["UTC", "utc", "Utc", "uTc"])
    def test_utc_string_case_insensitive(self, utc_variant: str):
        result = parse_timezone(utc_variant)
        assert result is UTC

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
        result = parse_timezone(UTC)
        assert result is UTC

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
