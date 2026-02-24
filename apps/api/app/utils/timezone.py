"""
Timezone utilities for datetime manipulation.

This module provides functions to handle timezone operations while preserving
the actual time values (not converting them across timezones).
"""

from datetime import timezone as builtin_timezone
from typing import Union

import pytz


def parse_timezone(
    timezone_input: Union[str, builtin_timezone],
) -> Union[builtin_timezone, pytz.BaseTzInfo]:
    """
    Parse timezone input into a timezone object.

    Args:
        timezone_input: Either a timezone string name or timezone object

    Returns:
        Union[timezone, pytz.BaseTzInfo]: Parsed timezone object

    Raises:
        ValueError: If timezone string is invalid or unrecognized
    """
    if isinstance(timezone_input, str):
        # Handle common timezone string formats
        if timezone_input.upper() == "UTC":
            return builtin_timezone.utc

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
