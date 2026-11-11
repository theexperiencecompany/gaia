"""The local days a brief's series cover, and how real moments fall into them."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.constants.briefing import SERIES_WINDOW_DAYS
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.context import UserClock


@dataclass(frozen=True)
class SeriesWindow:
    """Consecutive local days, first_day included, on the user's clock."""

    first_day: date
    days: int
    tz: ZoneInfo

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
        return self.bounds(self.dates[-1])[1]

    def day_of(self, moment: datetime) -> date | None:
        """Return the local day a moment falls on, or None outside the window."""
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        day = aware.astimezone(self.tz).date()
        return day if self.first_day <= day < self.first_day + timedelta(days=self.days) else None


def daily_window(clock: UserClock) -> SeriesWindow:
    """Return the week ending today, today so far included."""
    today = clock.now_local.date()
    return SeriesWindow(
        first_day=today - timedelta(days=SERIES_WINDOW_DAYS - 1),
        days=SERIES_WINDOW_DAYS,
        tz=clock.tz,
    )


def week_window(clock: UserClock) -> SeriesWindow:
    """Return this week from Monday to today."""
    today = clock.now_local.date()
    return SeriesWindow(
        first_day=today - timedelta(days=today.weekday()),
        days=today.weekday() + 1,
        tz=clock.tz,
    )


def per_day(moments: Iterable[datetime], window: SeriesWindow) -> list[float]:
    """Count the moments on each day of the window, oldest day first."""
    counted = Counter(day for m in moments if (day := window.day_of(m)) is not None)
    return [float(counted[day]) for day in window.dates]


@dataclass(frozen=True)
class SeriesName:
    """Who a series is: its stable id, what it counts, and where from."""

    id: str
    label: str
    unit: str
    source: str
    app: str


def _series(name: SeriesName, shape: SeriesShape, points: list[SeriesPoint]) -> DataSeries:
    return DataSeries(
        id=name.id,
        label=name.label,
        unit=name.unit,
        source=name.source,
        app=name.app,
        shape=shape,
        points=points,
    )


def day_series(name: SeriesName, values: list[float], window: SeriesWindow) -> DataSeries | None:
    """Lay one value per window day out as a time series; None when every day is zero."""
    if not any(values):
        return None
    points = [
        SeriesPoint(x=day.isoformat(), y=value)
        for day, value in zip(window.dates, values, strict=True)
    ]
    return _series(name, SeriesShape.TIME_SERIES, points)


def categorical_series(name: SeriesName, points: list[SeriesPoint]) -> DataSeries | None:
    """Lay category values out as a categorical series; None when there are none."""
    return _series(name, SeriesShape.CATEGORICAL, points) if points else None
