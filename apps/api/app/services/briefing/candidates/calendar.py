"""Today's calendar events as candidates: the composition may lead with one, never group one."""

from datetime import date, datetime

from app.agents.prompts.brief_fact_prompts import (
    ALL_DAY,
    EVENT_ANSWERED,
    EVENT_GUESTS,
    EVENT_ON_CALENDAR,
    EVENT_ORGANIZED_BY,
    EVENT_UNTIL,
)
from app.constants.briefing import BriefAction
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import EVENT_TIME_FORMAT, BriefingEvent
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.formats import clock_time, short_weekday


def start_time(event: BriefingEvent) -> str | None:
    """Say the time an event starts on the user's clock, as every brief does; None all day."""
    return _clock(event.start) if event.start else None


def _clock(hhmm: str) -> str:
    return clock_time(datetime.strptime(hhmm, EVENT_TIME_FORMAT))


def event_detail(event: BriefingEvent) -> str | None:
    """Say what an event's line adds to its title and start: its end, where, which calendar, who and the user's answer."""
    parts = [
        EVENT_UNTIL.format(time=_clock(event.end)) if event.end else None,
        event.location,
        EVENT_ON_CALENDAR.format(calendar=event.calendar) if event.calendar else None,
        EVENT_ORGANIZED_BY.format(organizer=event.organizer) if event.organizer else None,
        EVENT_GUESTS.format(guests=event.guests) if event.guests else None,
        EVENT_ANSWERED.get(event.response),
    ]
    return " | ".join(part for part in parts if part) or None


def event_time(event: BriefingEvent, today: str) -> str | None:
    """Say when an event starts; one on another day than today names its weekday too."""
    on = "" if event.date == today else short_weekday(date.fromisoformat(event.date))
    return " ".join(part for part in (on, start_time(event)) if part) or None


def calendar_candidates(events: list[BriefingEvent], today: str) -> list[BriefCandidate]:
    """Return one candidate per event, timed in the user's own clock; today is its ISO date."""
    if not events:
        return []
    app = integration_name(GOOGLE_CALENDAR_INTEGRATION_ID)
    return [
        BriefCandidate(
            origin=CandidateOrigin.EVENT,
            source=GOOGLE_CALENDAR_INTEGRATION_ID,
            app=app,
            state=ItemState.NOTE,
            title=event.title,
            detail=" | ".join(
                part
                for part in (ALL_DAY if event.start is None else None, event_detail(event))
                if part
            )
            or None,
            time=event_time(event, today),
            action=BriefAction.ATTEND,
        )
        for event in events
    ]
