"""What the daily brief can say: one candidate per thing found, from every source, before selection.

Each producer in services/briefing/candidates/ turns one source (the user's apps, their
tracked todos, held results, approvals, reminders, failed runs, the calendar) into
candidates; the selection judge then picks the brief's sections from all of them.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.briefing_models import BriefingItemKind
from app.models.scout_models import Signal, SignalImportance


class CandidateKind(StrEnum):
    """Where a producer would file a candidate; the judge makes the final call."""

    NEEDS_YOU = "needs_you"
    UPDATE = "update"
    GAIA_DID = "gaia_did"
    EVENT = "event"


class BriefCandidate(BaseModel):
    """One thing the brief could tell the user, with the references its run writes back to."""

    #: An integration id, or GAIA_SOURCE for GAIA's own work.
    source: str
    app: str = Field(description="Display name: GitHub, Gmail, GAIA")
    kind: CandidateKind
    #: How the item reads in an edition when it is kept (waiting on you, failed, done...).
    state: BriefingItemKind
    #: The source's own words; the judge writes the brief's short title from them.
    title: str = Field(min_length=1)
    detail: str | None = None
    #: What the item asks or where it got to, when its producer knows; else the judge says.
    action: BriefAction | None = None
    outcome: BriefOutcome | None = None
    people: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
    url: str | None = None
    importance: SignalImportance = SignalImportance.NORMAL
    todo_id: str | None = None
    #: How many tracked todos this one candidate stands for (one subject, several todos).
    count: int = Field(default=1, ge=1)
    #: The held result it carries, cleared once the brief accounts for it.
    held_id: str | None = None
    #: The app signal it is, marked shown when the message speaks of it.
    signal: Signal | None = None
