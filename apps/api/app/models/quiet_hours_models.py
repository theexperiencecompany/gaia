"""The user's quiet hours: local hours in which GAIA holds what can wait for the morning."""

from datetime import datetime, time, timedelta
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.quiet_hours import QUIET_HOURS_END, QUIET_HOURS_START

# An hour on the user's own clock, 0 to 23.
LocalHour = Annotated[int, Field(ge=0, le=23)]


class QuietHours(BaseModel):
    """When the user's quiet hours start and end on their own clock; the span may cross midnight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    start_hour: LocalHour
    end_hour: LocalHour

    @model_validator(mode="after")
    def _spans_some_hours(self) -> Self:
        if self.start_hour == self.end_hour:
            raise ValueError("quiet hours must start and end at different hours")
        return self

    def contains(self, moment: datetime) -> bool:
        """Whether moment, on the user's own clock, falls inside these quiet hours."""
        if not self.enabled:
            return False
        if self.start_hour < self.end_hour:
            return self.start_hour <= moment.hour < self.end_hour
        return moment.hour >= self.start_hour or moment.hour < self.end_hour

    def end_after(self, moment: datetime) -> datetime:
        """Return moment, or the end of the quiet hours it falls in, on moment's own clock."""
        if not self.contains(moment):
            return moment
        crosses_midnight = self.start_hour > self.end_hour
        day = moment.date()
        if crosses_midnight and moment.hour >= self.start_hour:
            day += timedelta(days=1)
        return datetime.combine(day, time(self.end_hour), tzinfo=moment.tzinfo)


# What a user who never set their own quiet hours gets.
DEFAULT_QUIET_HOURS: Final = QuietHours(
    enabled=True, start_hour=QUIET_HOURS_START, end_hour=QUIET_HOURS_END
)
