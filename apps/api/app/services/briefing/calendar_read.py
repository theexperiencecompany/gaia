"""The user's calendar, read once per run over every day a brief covers, or why it went unread."""

from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from enum import StrEnum

from fastapi import HTTPException

from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_payload_models import EVENT_TIME_FORMAT, BriefingEvent, UnreadSource
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.scout_models import ScoutSkipReason
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.clock import DayWindow
from app.services.calendar_service import get_calendar_events
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.utils.errors import IntegrationNotConnectedError
from shared.py.wide_events import log


class CalendarGap(StrEnum):
    """Why a brief has no calendar to read."""

    NOT_CONNECTED = "not_connected"
    #: A connected calendar did not answer: nothing can be said about the day's events.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CalendarRead:
    """One read of the calendar: the brief's span's events and everything read, or why it went unread.

    An unread calendar is never the same as an empty one: gap says why, and both lists are empty.
    """

    #: The events starting in the brief's span (today, or the week ahead), ordered by start.
    events: list[BriefingEvent] = field(default_factory=list)
    #: Every event the read returned, as Google sent it, declined ones left out.
    raw: list[GoogleCalendarEventResource] = field(default_factory=list)
    gap: CalendarGap | None = None

    @property
    def tally(self) -> int | CalendarGap:
        """Return how many events the span holds, or why the calendar went unread."""
        return self.gap if self.gap is not None else len(self.events)

    @property
    def unread(self) -> list[UnreadSource]:
        """Name the calendar as a source the brief could not read, when a connected one did not answer."""
        if self.gap is not CalendarGap.UNAVAILABLE:
            return []
        return [
            UnreadSource(
                app=integration_name(GOOGLE_CALENDAR_INTEGRATION_ID), reason=ScoutSkipReason.FAILED
            )
        ]


async def fetch_calendar(
    user_id: str, start: datetime, end: datetime
) -> list[GoogleCalendarEventResource] | CalendarGap:
    """Return the user's calendar events from start to end as Google sends them, declined ones left out.

    A connected calendar that fails to answer, even for one of its calendars, is unavailable.
    """
    if GOOGLE_CALENDAR_INTEGRATION_ID not in await get_connected_integration_ids(user_id):
        return CalendarGap.NOT_CONNECTED
    try:
        response = await get_calendar_events(
            user_id, time_min=start.isoformat(), time_max=end.isoformat(), fetch_all=True
        )
    except (IntegrationNotConnectedError, HTTPException):
        log.warning("briefing.calendar_unavailable")
        return CalendarGap.UNAVAILABLE
    if response.calendars_failed:
        log.warning(
            "briefing.calendar_unavailable", calendars_failed=len(response.calendars_failed)
        )
        return CalendarGap.UNAVAILABLE
    return [event for event in response.events if not event.declined_by_user]


async def read_calendar(user_id: str, reach: DayWindow, span: DayWindow) -> CalendarRead:
    """Read the calendar once over reach and span together, and take the span's events from it."""
    raw = await fetch_calendar(user_id, min(reach.start, span.start), max(reach.end, span.end))
    if isinstance(raw, CalendarGap):
        return CalendarRead(gap=raw)
    return CalendarRead(events=events_in(raw, span), raw=raw)


def events_in(raw: list[GoogleCalendarEventResource], span: DayWindow) -> list[BriefingEvent]:
    """Return the events starting on the span's local days, ordered by start (all-day first)."""
    days = set(span.dates)
    events = [
        e
        for e in (_to_event(event, span.tz) for event in raw)
        if e is not None and date.fromisoformat(e.date) in days
    ]
    return sorted(events, key=lambda e: (e.date, e.start or ""))


def _to_event(event: GoogleCalendarEventResource, tz: tzinfo) -> BriefingEvent | None:
    start = event.start
    if start is None:
        return None
    if start.dateTime:
        local = datetime.fromisoformat(start.dateTime).astimezone(tz)
        ends = event.end.dateTime if event.end is not None else None
        end = datetime.fromisoformat(ends).astimezone(tz) if ends else None
        timed = end is not None and end > local and end.date() == local.date()
        day = local.date().isoformat()
        at = local.strftime(EVENT_TIME_FORMAT)
        until = end.strftime(EVENT_TIME_FORMAT) if end is not None and timed else None
    elif start.date:
        day, at, until = start.date, None, None
    else:
        return None
    return BriefingEvent(
        date=day,
        start=at,
        end=until,
        title=(event.summary or "").strip() or "Untitled event",
        location=event.location,
        calendar=event.calendarTitle,
        response=event.response,
        organizer=event.organizer_name,
        guests=event.guests,
    )
