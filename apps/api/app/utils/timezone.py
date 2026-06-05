"""
Timezone utilities for datetime manipulation.

This module provides functions to handle timezone operations while preserving
the actual time values (not converting them across timezones).
"""

from datetime import UTC, datetime, timezone as builtin_timezone
from typing import Union

import pytz


def parse_timezone(
    timezone_input: Union[str, builtin_timezone],
) -> Union[builtin_timezone, pytz.BaseTzInfo]:
    """Parse a timezone name or object into a timezone object.

    Raises ValueError on an unrecognized timezone string.
    """
    if isinstance(timezone_input, str):
        # Handle common timezone string formats
        if timezone_input.upper() == "UTC":
            return UTC

        try:
            # Try parsing as pytz timezone (e.g., 'America/New_York')
            pytz_tz = pytz.timezone(timezone_input)
            return pytz_tz
        except pytz.UnknownTimeZoneError:
            raise ValueError(
                f"Unknown timezone string: '{timezone_input}'. Use standard timezone names like 'UTC', 'America/New_York', 'Asia/Kolkata', etc."
            )

    elif isinstance(timezone_input, builtin_timezone):
        return timezone_input

    else:
        raise ValueError(
            f"Invalid timezone type: {type(timezone_input)}. Expected string or timezone object."
        )


def format_local_time(
    instant: datetime,
    timezone_name: str | None,
    fmt: str = "%I:%M %p %Z",
) -> str:
    """Render ``instant`` as a human-readable local time string.

    Converts ``instant`` (a tz-aware datetime) into ``timezone_name`` and formats
    it with ``fmt`` — defaulting to e.g. ``"10:22 PM PST"``. The leading zero on
    the 12-hour clock is stripped (``"09:05 AM"`` -> ``"9:05 AM"``). Falls back to
    UTC when the timezone is missing or invalid, so a bad/absent preference never
    raises into a notification path.
    """
    try:
        tz = parse_timezone(timezone_name or "UTC")
    except ValueError:
        tz = UTC
    local = instant.astimezone(tz)
    return local.strftime(fmt).lstrip("0")


def is_within_local_daytime(
    instant: datetime,
    timezone_name: str | None,
    start_hour: int,
    end_hour: int,
) -> bool:
    """Return whether ``instant`` falls inside the local daytime window.

    Converts ``instant`` (any tz-aware datetime) into ``timezone_name`` and
    checks whether the local hour is within ``[start_hour, end_hour)``. Used to
    avoid pushing proactive notifications during a user's night. Falls back to
    UTC when the timezone is missing or invalid.
    """
    tz = parse_timezone(timezone_name or "UTC")
    local_hour = instant.astimezone(tz).hour
    return start_hour <= local_hour < end_hour


# Commonly used timezone constants for convenience
TIMEZONE_UTC = UTC
TIMEZONE_KOLKATA = "Asia/Kolkata"
TIMEZONE_NEW_YORK = "America/New_York"
TIMEZONE_LONDON = "Europe/London"
TIMEZONE_TOKYO = "Asia/Tokyo"
