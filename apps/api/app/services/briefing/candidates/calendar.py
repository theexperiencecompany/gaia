"""Today's calendar events as candidates: the composition may lead with one, never group one."""

from datetime import date, datetime

from app.constants.briefing import BriefAction
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import BriefingEvent
from app.models.calendar_models import CalendarResponse
from app.services.briefing.candidates.app_names import integration_name


def start_time(event: BriefingEvent) -> str | None:
    """Say the time an event starts on the user's clock, as every brief does; None all day."""
    return datetime.strptime(event.start, "%H:%M").strftime("%-I:%M %p") if event.start else None


def _clock(hhmm: str) -> str:
    return datetime.strptime(hhmm, "%H:%M").strftime("%-I:%M %p")


_ANSWERED: dict[CalendarResponse, str] = {
    CalendarResponse.TENTATIVE: "the user answered tentative",
    CalendarResponse.NEEDS_ACTION: "the user has not answered the invite",
}


def event_detail(event: BriefingEvent) -> str | None:
    """Say what an event's line adds to its title and start: its end, where, which calendar, who and the user's answer."""
    parts = [
        f"until {_clock(event.end)}" if event.end else None,
        event.location,
        f"on the {event.calendar} calendar" if event.calendar else None,
        f"organized by {event.organizer}" if event.organizer else None,
        f"{event.guests} other(s) invited" if event.guests else None,
        _ANSWERED.get(event.response),
    ]
    return " | ".join(part for part in parts if part) or None


def event_time(event: BriefingEvent, today: str) -> str | None:
    """Say when an event starts; one on another day than today names its weekday too."""
    day = "" if event.date == today else date.fromisoformat(event.date).strftime("%a")
    return " ".join(part for part in (day, start_time(event)) if part) or None


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
                for part in ("all day" if event.start is None else None, event_detail(event))
                if part
            )
            or None,
            time=event_time(event, today),
            action=BriefAction.ATTEND,
        )
        for event in events
    ]
