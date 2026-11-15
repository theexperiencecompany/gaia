"""Say a date or time the way a person would, in the user's zone: tomorrow, Fri 3 pm, 21 Nov."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import re
from typing import Self

from app.utils.timezone import Timezone

_ISO_DATE_START = re.compile(r"^\d{4}-\d{2}-\d{2}")
_BARE_DATE_CHARS = 10
_RELATIVE_DAYS = {-1: "yesterday", 0: "today", 1: "tomorrow"}
_DAYS_NAMED_BY_WEEKDAY = 7
_NOON = 12


@dataclass(frozen=True)
class UserClock:
    """Where the user is in time: their zone and the moment "today" is counted from."""

    tz: Timezone
    now: datetime

    @classmethod
    def current(cls, tz: Timezone) -> Self:
        """Return the user's clock as of this instant."""
        return cls(tz, datetime.now(UTC))


def parse_moment(value: str) -> date | datetime | None:
    """Return a bare date as a date and a timestamp as a datetime; None when it is neither."""
    text = value.strip()
    if not _ISO_DATE_START.match(text):
        return None
    try:
        if len(text) == _BARE_DATE_CHARS:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def say_moment(moment: date | datetime, clock: UserClock) -> str:
    """Name a moment relative to the user's now; a naive timestamp is already their local time."""
    tz = clock.tz
    today = tz.localize(clock.now).date()
    if not isinstance(moment, datetime):
        return _say_day(moment, today)
    local = tz.localize(moment) if moment.tzinfo else moment
    day = _say_day(local.date(), today)
    if local.time() == time(0):
        return day
    # "tomorrow at 3 pm" but "Fri 3 pm".
    joiner = " at " if (local.date() - today).days in _RELATIVE_DAYS else " "
    return f"{day}{joiner}{_say_clock(local)}"


def _say_day(day: date, today: date) -> str:
    offset = (day - today).days
    if offset in _RELATIVE_DAYS:
        return _RELATIVE_DAYS[offset]
    if 1 < offset < _DAYS_NAMED_BY_WEEKDAY:
        return day.strftime("%a")
    if day.year == today.year:
        return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"
    return f"{day.day} {day.strftime('%b')} {day.year}"


def _say_clock(local: datetime) -> str:
    hour = local.hour % _NOON or _NOON
    minutes = f":{local.minute:02d}" if local.minute else ""
    return f"{hour}{minutes} {'am' if local.hour < _NOON else 'pm'}"
