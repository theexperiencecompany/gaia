"""The user's clock: their local day, the runs of local days a brief covers, and how moments fall into them."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from app.models.brief_document_models import BriefingModel
from app.services.briefing.formats import day, long_day
from app.utils.timezone import Timezone, as_utc


@dataclass(frozen=True)
class DayWindow:
    """Consecutive local days, first_day included, on the user's clock."""

    first_day: date
    days: int
    tz: tzinfo

    @property
    def dates(self) -> list[date]:
        return [self.first_day + timedelta(days=n) for n in range(self.days)]

    def bounds(self, day: date) -> tuple[datetime, datetime]:
        """Return one local day's midnight and the next, in UTC."""
        start = datetime.combine(day, time.min, tzinfo=self.tz)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self.tz)
        return start.astimezone(UTC), end.astimezone(UTC)

    @property
    def start(self) -> datetime:
        """The first day's local midnight, in UTC."""
        return self.bounds(self.first_day)[0]

    @property
    def end(self) -> datetime:
        """The midnight after the last day, in UTC."""
        return self.bounds(self.first_day + timedelta(days=self.days - 1))[1]

    def day_of(self, moment: datetime) -> date | None:
        """Return the local day a moment falls on, or None outside the window."""
        day = _local_day(moment, self.tz)
        return day if self.first_day <= day < self.first_day + timedelta(days=self.days) else None


def _local_day(moment: datetime, tz: tzinfo) -> date:
    """Return the local day a moment falls on; a naive moment is UTC, as Mongo stores it."""
    return as_utc(moment).astimezone(tz).date()


@dataclass(frozen=True)
class UserClock:
    tz: tzinfo
    now_local: datetime
    date_str: str
    day_of_year: int

    @property
    def today(self) -> date:
        return self.now_local.date()

    def day_of(self, moment: datetime) -> date:
        """Return the user's local day a moment falls on; a naive moment is UTC, as Mongo stores it."""
        return _local_day(moment, self.tz)

    def days(self, first_day: date, days: int) -> DayWindow:
        """Return days local days from first_day on this clock."""
        return DayWindow(first_day=first_day, days=days, tz=self.tz)

    def day_start(self, days_ago: int = 0) -> datetime:
        """Return the local midnight days_ago days back (ahead when negative), in UTC."""
        return self.days(self.today - timedelta(days=days_ago), 1).start

    def days_ending_today(self, days: int) -> DayWindow:
        """Return the days local days ending today, today so far included."""
        return self.days(self.today - timedelta(days=days - 1), days)

    def this_week(self) -> DayWindow:
        """Return this week from Monday to today."""
        return self.days_ending_today(self.today.weekday() + 1)

    def days_ahead(self, days: int) -> DayWindow:
        """Return the days local days starting tomorrow."""
        return self.days(self.today + timedelta(days=1), days)


def resolve_clock(user_timezone: str | None) -> UserClock:
    """Return the user's clock on their stored zone: an IANA name or a ±HH:MM offset."""
    tz = Timezone.parse(user_timezone).tzinfo
    now_local = datetime.now(tz)
    return UserClock(
        tz=tz,
        now_local=now_local,
        date_str=now_local.date().isoformat(),
        day_of_year=now_local.timetuple().tm_yday,
    )


def due_on(due_at: datetime, clock: UserClock) -> str:
    """Say a due date the way the brief does, on the user's own day: today, or its weekday and date."""
    on = clock.day_of(due_at)
    return "today" if on.isoformat() == clock.date_str else day(on)


def when_sent(last: BriefingModel, clock: UserClock) -> str:
    """Name the last brief's day as the user would: yesterday, or its weekday and date."""
    sent = date.fromisoformat(last.date)
    if sent == clock.today - timedelta(days=1):
        return "yesterday"
    return f"on {long_day(sent)}"
