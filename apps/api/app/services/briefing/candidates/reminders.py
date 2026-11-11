"""Reminders due today as candidates: what the user asked to be reminded of."""

from datetime import datetime

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefAction
from app.db.repositories.reminders import reminder_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.reminder_models import StaticReminderPayload


async def reminder_candidates(
    user_id: str, day_start: datetime, day_end: datetime
) -> list[BriefCandidate]:
    """Return each armed reminder firing between the user's local day start and end."""
    return [
        BriefCandidate(
            source=GAIA_SOURCE,
            app=GAIA_APP_NAME,
            state="you",
            title=reminder.payload.title,
            detail=reminder.payload.body or None,
            due_at=reminder.scheduled_at,
            action=BriefAction.ATTEND,
        )
        for reminder in await reminder_repository.find_scheduled_between(
            user_id, day_start, day_end
        )
        if isinstance(reminder.payload, StaticReminderPayload)
    ]
