"""What a brief can say: one candidate per thing found, from every source, before composition.

Each producer in services/briefing/candidates/ turns one source (the user's apps, their
tracked todos, held results, approvals, reminders, failed runs, the calendar) into
candidates; they are the fact pool's items, which the composition places by id.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefAction, BriefOutcome
from app.constants.todos import TodoCompleter
from app.models.brief_item_models import ItemState
from app.models.scout_models import Signal, SignalImportance, SignalMemoryDocument


class CandidateOrigin(StrEnum):
    """The producer that found a candidate, which decides where the brief may use it."""

    #: GAIA's tracked work: waiting on the user, failed, running or done since the last brief.
    TRACKED = "tracked"
    #: A dated todo of the user's own, due before the brief's span ends.
    OWN_TODO = "own_todo"
    #: An undated todo of the user's own: on their list, not news, so it never leads.
    BACKLOG = "backlog"
    #: A todo the user finished themselves, which only the weekly recaps.
    USER_DONE = "user_done"
    APPROVAL = "approval"
    REMINDER = "reminder"
    FAILED_RUN = "failed_run"
    APP_SIGNAL = "app_signal"
    #: A result a workflow or todo run held for the brief.
    HELD = "held"
    #: A calendar event: the edition draws the day's calendar itself, so it can only lead.
    EVENT = "event"


class OutsideRef(BaseModel):
    """The outside thing a candidate is about, which another source may find too."""

    model_config = ConfigDict(frozen=True)

    integration_id: str
    external_id: str


class GaiaRefKind(StrEnum):
    """What GAIA's own id names, when a candidate is no todo and no outside thing."""

    TODO = "todo"
    APPROVAL = "approval"
    WORKFLOW = "workflow"
    REMINDER = "reminder"


class GaiaRef(BaseModel):
    """GAIA's own id for what a candidate is; it prints as the key signal memory stores it under."""

    model_config = ConfigDict(frozen=True)

    kind: GaiaRefKind
    id: str

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"


class BriefCandidate(BaseModel):
    """One thing the brief could tell the user, with the references its run writes back to."""

    origin: CandidateOrigin
    #: An integration id, or GAIA_SOURCE for GAIA's own work.
    source: str
    app: str = Field(description="Display name: GitHub, Gmail, GAIA")
    #: How the item reads in an edition when it is kept (waiting on you, failed, done...).
    state: ItemState
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
    #: The outside thing it is about, which another source may find too.
    ref: OutsideRef | None = None
    #: The other sources that found the same thing, folded into this one item.
    also_in: list[str] = Field(default_factory=list)
    #: GAIA's own id for what it is when it is no todo or outside thing.
    seen_as: GaiaRef | None = None
    #: Whether GAIA can act on it (it has tools that change its app), so an offer about it is real.
    gaia_acts: bool = False
    #: What earlier briefs remember of it, as it stood before today; None the first time.
    memory: SignalMemoryDocument | None = None
    #: Whether its state changed since an earlier brief saw it.
    moved: bool = False

    @property
    def is_event(self) -> bool:
        """Whether it is a calendar event, which can only lead."""
        return self.origin is CandidateOrigin.EVENT

    @property
    def backlog(self) -> bool:
        """Whether it is an undated todo of the user's own, which never leads."""
        return self.origin is CandidateOrigin.BACKLOG

    @property
    def is_repeat(self) -> bool:
        """Whether an earlier brief already showed it, unchanged: still open, not news."""
        return self.memory is not None and self.memory.times_shown > 0 and not self.moved

    @property
    def is_news(self) -> bool:
        """Whether it is something the user has not been told: no event, backlog or repeat."""
        return not (self.is_event or self.backlog or self.is_repeat)
