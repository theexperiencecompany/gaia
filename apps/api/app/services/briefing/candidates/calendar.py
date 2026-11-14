"""Today's calendar events as candidates: the judge may lead with one, never file one elsewhere."""

from app.constants.briefing import BriefAction
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import BriefingEvent
from app.services.briefing.candidates.app_names import integration_name


def calendar_candidates(events: list[BriefingEvent]) -> list[BriefCandidate]:
    """Return one candidate per event, timed in the user's own clock."""
    if not events:
        return []
    app = integration_name(GOOGLE_CALENDAR_INTEGRATION_ID)
    return [
        BriefCandidate(
            source=GOOGLE_CALENDAR_INTEGRATION_ID,
            app=app,
            kind=CandidateKind.EVENT,
            state="note",
            title=event.title,
            detail=" | ".join(
                part
                for part in (f"at {event.start}" if event.start else "all day", event.location)
                if part
            ),
            action=BriefAction.ATTEND,
        )
        for event in events
    ]
