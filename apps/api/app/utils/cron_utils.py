"""
Cron utilities for reminder and workflow scheduling.

Timezone handling is delegated entirely to :class:`app.utils.timezone.Timezone`
— this module never parses a timezone string itself.
"""

from datetime import UTC, datetime

from croniter import croniter

from app.utils.timezone import Timezone
from shared.py.wide_events import log


class CronError(Exception):
    """Exception raised for cron-related errors."""

    pass


def validate_cron_expression(cron_expr: str) -> bool:
    """Validate a cron expression.

    Args:
        cron_expr: Cron expression to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        croniter(cron_expr)
        return True
    except (ValueError, TypeError):
        return False


def get_next_run_time(
    cron_expr: str,
    base_time: datetime | None = None,
    tz: Timezone | None = None,
) -> datetime:
    """Get the next scheduled run time for a cron expression, returned in UTC.

    The cron fields are interpreted as wall-clock time in ``tz`` (the schedule's
    own timezone), so ``"0 9 * * *"`` with ``tz=Timezone.parse("Asia/Kolkata")``
    fires at 09:00 IST. When ``tz`` is omitted the cron is interpreted in
    ``base_time``'s OWN zone — a tz-aware base carries the user's zone (e.g. a
    reminder's local "now") and must not be silently reinterpreted in UTC; only a
    naive/absent base falls back to UTC. ``base_time`` defaults to "now".

    Args:
        cron_expr: Cron expression (e.g. "0 8 * * *" for daily at 8 AM)
        base_time: Base time to calculate from (defaults to now in UTC)
        tz: Schedule timezone the cron is interpreted in (defaults to base's zone)

    Returns:
        Next scheduled datetime in UTC

    Raises:
        CronError: If the cron expression is invalid
    """
    if not validate_cron_expression(cron_expr):
        raise CronError(f"Invalid cron expression: {cron_expr}")

    if base_time is None:
        base_time = datetime.now(UTC)
    elif base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=UTC)

    # An explicit schedule tz wins; otherwise interpret the cron in the base
    # time's own (now tz-aware) zone rather than forcing UTC.
    zone = tz or Timezone.parse(base_time.tzinfo)
    log.set(cron_expr=cron_expr, user_timezone=zone.value)
    base = base_time.astimezone(zone.tzinfo)

    try:
        cron = croniter(cron_expr, base)
        next_time: datetime = cron.get_next(datetime)
        if next_time.tzinfo is None:
            next_time = next_time.replace(tzinfo=zone.tzinfo)
        return next_time.astimezone(UTC)
    except Exception as e:
        raise CronError(f"Failed to calculate next run time: {e!s}")


def calculate_next_occurrences(
    cron_expr: str, count: int, base_time: datetime | None = None
) -> list[datetime]:
    """
    Calculate the next N occurrences of a cron expression.

    Args:
        cron_expr: Cron expression
        count: Number of occurrences to calculate
        base_time: Base time to calculate from (defaults to current UTC time)

    Returns:
        List of next scheduled datetimes in UTC

    Raises:
        CronError: If cron expression is invalid
    """
    if not validate_cron_expression(cron_expr):
        raise CronError(f"Invalid cron expression: {cron_expr}")

    if count <= 0:
        return []

    if base_time is None:
        base_time = datetime.now(UTC)
    elif base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=UTC)

    try:
        cron = croniter(cron_expr, base_time)
        occurrences: list[datetime] = []

        for _ in range(count):
            next_time: datetime = cron.get_next(datetime)
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=UTC)
            occurrences.append(next_time)

        return occurrences
    except Exception as e:
        raise CronError(f"Failed to calculate next occurrences: {e!s}")


# Common cron expressions for easy reference
COMMON_CRON_EXPRESSIONS = {
    "every_minute": "* * * * *",
    "every_5_minutes": "*/5 * * * *",
    "every_15_minutes": "*/15 * * * *",
    "every_30_minutes": "*/30 * * * *",
    "hourly": "0 * * * *",
    "daily_8am": "0 8 * * *",
    "daily_noon": "0 12 * * *",
    "daily_6pm": "0 18 * * *",
    "weekly_monday_9am": "0 9 * * 1",
    "monthly_first_day": "0 9 1 * *",
    "yearly_jan_1st": "0 9 1 1 *",
}
