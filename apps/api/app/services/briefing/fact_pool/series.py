"""How a brief's series are laid out: one value per local day of its window, or one per category."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.clock import DayWindow


def per_day(moments: Iterable[datetime], window: DayWindow) -> list[float]:
    """Count the moments on each day of the window, oldest day first."""
    counted = Counter(day for m in moments if (day := window.day_of(m)) is not None)
    return [float(counted[day]) for day in window.dates]


@dataclass(frozen=True)
class SeriesName:
    """Who a series is: its stable id, what it counts, and where from."""

    id: str
    label: str
    unit: str | None
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


def day_series(name: SeriesName, values: list[float], window: DayWindow) -> DataSeries | None:
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
