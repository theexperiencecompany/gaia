"""The one place the backend reads the current time, so a test can move it."""

from datetime import UTC, datetime


def now() -> datetime:
    """Return the current instant as a UTC-aware datetime."""
    return datetime.now(UTC)
