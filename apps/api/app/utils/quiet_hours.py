"""Whether a moment on the user's clock falls in their quiet hours, and when those hours end."""

from datetime import datetime, time, timedelta

from app.constants.quiet_hours import QUIET_HOURS_END, QUIET_HOURS_START


def in_quiet_hours(moment: datetime) -> bool:
    """Whether moment, on the user's own clock, falls in their quiet hours, which span midnight."""
    return moment.hour >= QUIET_HOURS_START or moment.hour < QUIET_HOURS_END


def after_quiet_hours(moment: datetime) -> datetime:
    """Return moment, or the end of the quiet hours it falls in, on moment's own clock."""
    if not in_quiet_hours(moment):
        return moment
    day = moment.date() + timedelta(days=1) if moment.hour >= QUIET_HOURS_START else moment.date()
    return datetime.combine(day, time(QUIET_HOURS_END), tzinfo=moment.tzinfo)
