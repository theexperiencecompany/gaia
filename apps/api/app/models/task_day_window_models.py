"""A user's task day as UTC instants: the one place today, upcoming and overdue bounds are decided."""

from datetime import UTC, datetime, time, timedelta
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from app.constants.tasks import TASK_UPCOMING_DAYS
from app.utils.timezone import Timezone

# due ranges are inclusive; Mongo keeps milliseconds, so one microsecond before a boundary is its last instant.
_LAST_INSTANT_BEFORE = timedelta(microseconds=1)


class DueRange(NamedTuple):
    """An inclusive due-date range."""

    start: datetime
    end: datetime


class TaskDayWindow(BaseModel):
    """A user's task day as UTC instants: today, the upcoming days after it, and the overdue cutoff.

    Today is the user's local calendar day; upcoming is the local days after today;
    an open task due before today_start is overdue. Every surface buckets tasks with this.
    """

    model_config = ConfigDict(frozen=True)

    today_start: datetime
    tomorrow_start: datetime
    upcoming_end: datetime

    @classmethod
    def for_timezone(
        cls, timezone: Timezone, now: datetime, upcoming_days: int = TASK_UPCOMING_DAYS
    ) -> "TaskDayWindow":
        """Build the window around now on the wall clock of timezone."""
        if now.tzinfo is None:
            raise ValueError("TaskDayWindow needs a timezone-aware now")
        local_today = timezone.localize(now).date()

        def local_midnight(days_after_today: int) -> datetime:
            day = local_today + timedelta(days=days_after_today)
            return datetime.combine(day, time.min, tzinfo=timezone.tzinfo).astimezone(UTC)

        return cls(
            today_start=local_midnight(0),
            tomorrow_start=local_midnight(1),
            upcoming_end=local_midnight(1 + upcoming_days),
        )

    @property
    def today(self) -> DueRange:
        return DueRange(self.today_start, self.tomorrow_start - _LAST_INSTANT_BEFORE)

    @property
    def upcoming(self) -> DueRange:
        return DueRange(self.tomorrow_start, self.upcoming_end - _LAST_INSTANT_BEFORE)
