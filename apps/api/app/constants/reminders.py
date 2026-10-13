"""Reminder scheduling constants."""

from datetime import timedelta

# A reminder created without an explicit stop_after stops recurring this long after creation.
REMINDER_DEFAULT_LIFETIME = timedelta(days=180)
