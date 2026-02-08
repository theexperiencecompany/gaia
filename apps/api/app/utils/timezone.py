"""
Timezone utilities for datetime manipulation.

This module provides functions to handle timezone operations while preserving
the actual time values (not converting them across timezones).
"""

from datetime import datetime, tzinfo
from datetime import timezone as builtin_timezone
from typing import Optional, Union

import pytz


def replace_timezone_info(
    target_datetime: Union[str, datetime],
    new_timezone: Union[str, builtin_timezone, None] = None,
    timezone_source: Union[str, datetime, None] = None,
) -> datetime:
    """
    Replace timezone information in a datetime while keeping the same time values.

    This function does NOT convert time across timezones. It only changes the timezone
    metadata. For example, if you have "7:00 PM UTC" and want it to show as
    "7:00 PM UTC+5:30", the time stays 7:00 PM but the timezone info changes.

    Example:
        >>> dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)  # 7PM UTC
        >>> result = replace_timezone_info(dt, 'Asia/Kolkata')
        >>> # Result: 7PM in Asia/Kolkata timezone (not 12:30AM next day!)

    Args:
        target_datetime: The datetime whose timezone info should be replaced.
                        Can be a string (ISO format) or datetime object.
        new_timezone: The new timezone to apply. Can be:
                     - String timezone name (e.g., 'America/New_York', 'UTC')
                     - timezone object
                     - None (will extract from timezone_source)
        timezone_source: Alternative source to extract timezone from.
                        Can be a datetime object or ISO string with timezone info.
                        Used when new_timezone is None.

    Returns:
        datetime: New datetime object with replaced timezone info but same time values.

    Raises:
        ValueError: If neither new_timezone nor timezone_source is provided,
                   or if timezone cannot be determined or is invalid.
    """
    # Convert string datetime to datetime object if needed
    if isinstance(target_datetime, str):
        target_datetime = datetime.fromisoformat(target_datetime)

    # Validate that we have some way to determine the new timezone
    if new_timezone is None and timezone_source is None:
        raise ValueError(
            "Either 'new_timezone' or 'timezone_source' must be provided to determine the target timezone."
        )

    # Determine the target timezone to apply
    target_timezone_info: Optional[tzinfo] = None

    if new_timezone is not None:
        target_timezone_info = parse_timezone(new_timezone)
    else:
        # Extract timezone from timezone_source
        if isinstance(timezone_source, str):
            timezone_source = datetime.fromisoformat(timezone_source)
        elif timezone_source is None:
            # Fallback to current UTC time if timezone_source is None
            timezone_source = datetime.now(tz=builtin_timezone.utc)

        target_timezone_info = timezone_source.tzinfo

    if target_timezone_info is None:
        raise ValueError(
            "Could not determine target timezone from provided parameters."
        )

    # Replace timezone info while keeping the same time values
    # This is the key operation: replace() keeps the time but changes timezone metadata
    result_datetime = target_datetime.replace(tzinfo=target_timezone_info)

    return result_datetime


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


def convert_datetime_to_timezone(
    source_datetime: Union[str, datetime],
    target_timezone: Union[str, builtin_timezone],
) -> datetime:
    """
    Actually convert a datetime from one timezone to another (changes time values).

    This function DOES convert time across timezones. Use this when you want to
    know what time it is in a different timezone.

    Example:
        >>> utc_dt = datetime(2025, 6, 18, 19, 0, 0, tzinfo=timezone.utc)  # 7PM UTC
        >>> kolkata_dt = convert_datetime_to_timezone(utc_dt, 'Asia/Kolkata')
        >>> # Result: 12:30AM next day in Asia/Kolkata (actual time conversion)

    Args:
        source_datetime: The datetime to convert (string or datetime object)
        target_timezone: Target timezone (string name or timezone object)

    Returns:
        datetime: Converted datetime in the target timezone

    Raises:
        ValueError: If timezone is invalid or datetime has no timezone info
    """
    # Convert string to datetime if needed
    if isinstance(source_datetime, str):
        source_datetime = datetime.fromisoformat(source_datetime)

    # Ensure source datetime has timezone info
    if source_datetime.tzinfo is None:
        raise ValueError(
            "Source datetime must have timezone information for conversion."
        )

    # Parse target timezone
    target_tz = parse_timezone(target_timezone)

    # Perform the actual timezone conversion
    converted_datetime = source_datetime.astimezone(target_tz)

    return converted_datetime


def set_timezone_preserving_time(
    target_datetime: Union[str, datetime],
    timezone_name: str,
) -> datetime:
    """
    Convenience function to set timezone while preserving time values.

    This is a simplified version of replace_timezone_info() for the most common use case.

    Example:
        >>> dt_string = "2025-06-18T19:00:00"  # 7PM, no timezone
        >>> result = set_timezone_preserving_time(dt_string, 'Asia/Kolkata')
        >>> # Result: 7PM in Asia/Kolkata timezone

    Args:
        target_datetime: The datetime to modify (string or datetime object)
        timezone_name: Timezone name (e.g., 'UTC', 'Asia/Kolkata', 'America/New_York')

    Returns:
        datetime: Datetime with the specified timezone, same time values
    """
    return replace_timezone_info(target_datetime, new_timezone=timezone_name)


def add_timezone_info(
    target_datetime: Union[str, datetime],
    timezone_name: str,
) -> datetime:
    """
    Add timezone info to a datetime if it doesn't have one, while preserving time values.

    Args:
        target_datetime: The datetime to modify (string or datetime object)
        timezone_name: Timezone name (e.g., 'UTC', 'Asia/Kolkata', 'America/New_York')

    Returns:
        datetime: Datetime with the specified timezone, same time values
    """
    # Convert string datetime to datetime object if needed
    if isinstance(target_datetime, str):
        target_datetime = datetime.fromisoformat(target_datetime)

    # Parse the target timezone
    target_timezone_info = parse_timezone(timezone_name)

    # If the datetime already has timezone info, just return it
    if target_datetime.tzinfo is not None:
        return target_datetime

    # Otherwise, replace the timezone info while keeping the same time values
    return target_datetime.replace(tzinfo=target_timezone_info)


def get_timezone_from_datetime(target_datetime: Union[str, datetime]) -> str:
    """
    Get the timezone name from a datetime object or string.

    Args:
        target_datetime: The datetime to extract timezone from (string or datetime object)

    Returns:
        str: The name of the timezone (e.g., 'UTC', 'Asia/Kolkata')

    Raises:
        ValueError: If the datetime has no timezone info
    """
    if isinstance(target_datetime, str):
        target_datetime = datetime.fromisoformat(target_datetime)

    if target_datetime.tzinfo is None:
        raise ValueError(
            "Datetime must have timezone information to extract timezone name."
        )

    tz_name = target_datetime.tzinfo.tzname(target_datetime)
    if not tz_name:
        raise ValueError("Could not determine timezone name from datetime.")

    return tz_name


# Commonly used timezone constants for convenience
TIMEZONE_UTC = builtin_timezone.utc
TIMEZONE_KOLKATA = "Asia/Kolkata"
TIMEZONE_NEW_YORK = "America/New_York"
TIMEZONE_LONDON = "Europe/London"
TIMEZONE_TOKYO = "Asia/Tokyo"
