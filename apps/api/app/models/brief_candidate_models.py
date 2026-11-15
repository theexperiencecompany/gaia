"""What a brief can say: one candidate per thing found, from every source, before composition.

Each producer in services/briefing/candidates/ turns one source (the user's apps, their
tracked todos, held results, approvals, reminders, failed runs, the calendar) into
candidates; they are the fact pool's items, which the composition places by id.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants.briefing import BriefAction, BriefOutcome
from app.constants.todos import TodoCompleter
from app.models.briefing_models import BriefingItemKind
from app.models.scout_models import Signal, SignalImportance, SignalMemoryDocument


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
    #: Who closed a done todo; None for anything else, or a tracked one closed before it was recorded.
    finished_by: TodoCompleter | None = None
    #: Where open tracked work stands when GAIA is not simply working on it ("paused: ...").
    standing: str | None = None
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
    #: The outside thing it is about, as integration:id, which another source may find too.
    ref: str | None = None
    #: The other sources that found the same thing, folded into this one item.
    also_in: list[str] = Field(default_factory=list)
    #: GAIA's own id for what it is when it is no todo or outside thing ("approval:<id>").
    seen_as: str | None = None
    #: An undated todo of the user's own: on their list, not news, so it never leads.
    backlog: bool = False
    #: Whether GAIA can act on it (it has tools that change its app), so an offer about it is real.
    gaia_acts: bool = False
    #: What earlier briefs remember of it, as it stood before today; None the first time.
    memory: SignalMemoryDocument | None = None
    #: Whether its state changed since an earlier brief saw it.
    moved: bool = False

    @property
    def is_repeat(self) -> bool:
        """Whether an earlier brief already showed it, unchanged: still open, not news."""
        return self.memory is not None and self.memory.times_shown > 0 and not self.moved

    @property
    def is_news(self) -> bool:
        """Whether it is something the user has not been told: no event, backlog or repeat."""
        return not (self.is_event or self.backlog or self.is_repeat)
