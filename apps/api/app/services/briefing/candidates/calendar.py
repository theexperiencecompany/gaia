"""Today's calendar events as candidates: the composition may lead with one, never group one."""

from datetime import date, datetime

from app.constants.briefing import BriefAction
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import BriefingEvent
from app.services.briefing.candidates.app_names import integration_name


def event_time(event: BriefingEvent, today: str) -> str | None:
    """Say when an event starts; one on another day than today names its weekday too."""
    day = "" if event.date == today else date.fromisoformat(event.date).strftime("%a")
    start = datetime.strptime(event.start, "%H:%M").strftime("%-I:%M %p") if event.start else ""
    return " ".join(part for part in (day, start) if part) or None


def calendar_candidates(events: list[BriefingEvent], today: str) -> list[BriefCandidate]:
    """Return one candidate per event, timed in the user's own clock; today is its ISO date."""
    if not events:
        return []
    app = integration_name(GOOGLE_CALENDAR_INTEGRATION_ID)
    return [
        BriefCandidate(
            source=GOOGLE_CALENDAR_INTEGRATION_ID,
            app=app,
            is_event=True,
            state="note",
            title=event.title,
            detail=" | ".join(
                part for part in (None if event.start else "all day", event.location) if part
            )
            or None,
            time=event_time(event, today),
            action=BriefAction.ATTEND,
        )
        for event in events
    ]
