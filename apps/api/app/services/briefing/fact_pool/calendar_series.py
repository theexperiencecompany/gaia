"""Meeting hours per day, from the user's calendar: the time timed events hold, overlaps counted once.

All-day events and Google's focus time, out-of-office and working-location entries are
not meetings. An event that crosses midnight counts on each day for the hours it holds.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_pool_models import DataSeries
from app.models.calendar_models import GoogleCalendarEventResource
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.fact_pool.window import SeriesName, SeriesWindow, day_series

#: The eventType Google gives an ordinary event; any other type is not a meeting.
_MEETING_EVENT_TYPE = "default"
_SECONDS_PER_HOUR = 3600
#: Hours are said to a tenth: "2.5 hours".
_HOURS_DECIMALS = 1


def _interval(event: GoogleCalendarEventResource) -> tuple[datetime, datetime] | None:
    if event.eventType not in (None, _MEETING_EVENT_TYPE):
        return None
    if event.start is None or event.end is None:
        return None
    if event.start.dateTime is None or event.end.dateTime is None:
        return None
    start = datetime.fromisoformat(event.start.dateTime).astimezone(UTC)
    end = datetime.fromisoformat(event.end.dateTime).astimezone(UTC)
    return (start, end) if end > start else None


def _covered_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    """Return the seconds the intervals cover together, each overlap once."""
    total = 0.0
    reach: datetime | None = None
    for start, end in sorted(intervals):
        if reach is not None and start < reach:
            start = reach
        if end > start:
            total += (end - start).total_seconds()
        reach = end if reach is None else max(reach, end)
    return total


def calendar_series(
    raw: Sequence[GoogleCalendarEventResource], window: SeriesWindow
) -> list[DataSeries]:
    """Return the hours meetings hold on each day of the window; nothing when none were held."""
    intervals = [span for event in raw if (span := _interval(event)) is not None]
    hours: list[float] = []
    for day in window.dates:
        day_start, day_end = window.bounds(day)
        clipped = [
            (max(start, day_start), min(end, day_end))
            for start, end in intervals
            if start < day_end and end > day_start
        ]
        hours.append(round(_covered_seconds(clipped) / _SECONDS_PER_HOUR, _HOURS_DECIMALS))
    name = SeriesName(
        id="calendar_meeting_hours",
        label="Meeting hours",
        unit="hours",
        source=GOOGLE_CALENDAR_INTEGRATION_ID,
        app=integration_name(GOOGLE_CALENDAR_INTEGRATION_ID),
    )
    series = day_series(name, hours, window)
    return [series] if series is not None else []
