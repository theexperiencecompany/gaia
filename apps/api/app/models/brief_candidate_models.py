"""What a brief can say: one candidate per thing found, from every source, before composition.

Each producer in services/briefing/candidates/ turns one source (the user's apps, their
tracked todos, held results, approvals, reminders, failed runs, the calendar) into
candidates; they are the fact pool's items, which the composition places by id.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.briefing_models import BriefingItemKind
from app.models.scout_models import Signal, SignalImportance


class BriefCandidate(BaseModel):
    """One thing the brief could tell the user, with the references its run writes back to."""

    #: An integration id, or GAIA_SOURCE for GAIA's own work.
    source: str
    app: str = Field(description="Display name: GitHub, Gmail, GAIA")
    #: A calendar event: the edition draws the day's calendar itself, so it can only lead.
    is_event: bool = False
    #: How the item reads in an edition when it is kept (waiting on you, failed, done...).
    state: BriefingItemKind
    #: The source's own words; the composition writes the brief's short title from them.
    title: str = Field(min_length=1)
    detail: str | None = None
    #: What the item asks or where it got to, when its producer knows; else the composition says.
    action: BriefAction | None = None
    outcome: BriefOutcome | None = None
    people: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
    #: When it happens on the user's clock, as the brief says it ("4:00 PM"): an event's start.
    time: str | None = None
    url: str | None = None
    importance: SignalImportance = SignalImportance.NORMAL
    todo_id: str | None = None
    #: How many tracked todos this one candidate stands for (one subject, several todos).
    count: int = Field(default=1, ge=1)
    #: The held result it carries, cleared once the brief accounts for it.
    held_id: str | None = None
    #: The app signal it is, marked shown when the message speaks of it.
    signal: Signal | None = None
