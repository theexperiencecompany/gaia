"""Brief scouts: what a scout learned to watch, the signals it found, and what the brief remembers.

A scout answers one question per connected integration: what needs the user's attention
now or soon, read from the integration's current state. Its first (learn) run is a
read-only agent; the calls that run made are frozen as a playbook the daily brief replays
with no model, and each frozen result is read into signals by the paths the learn run named.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.models.playbook_models import PlaybookBody, PlaybookHandoffStepInput


class SignalImportance(StrEnum):
    """Whether a signal earns its own line in the brief, or a place in its app's group."""

    HIGH = "high"
    NORMAL = "normal"


class Signal(BaseModel):
    """One thing in one integration that needs the user's attention now or soon."""

    integration_id: str
    app: str = Field(description="The integration's display name")
    external_id: str = Field(min_length=1, description="The item's id inside the integration")
    kind: str = Field(description="What the item is to the user, e.g. 'issue assigned to you'")
    title: str = Field(min_length=1)
    why: str | None = Field(default=None, description="Why it needs attention now")
    importance: SignalImportance = SignalImportance.NORMAL
    due_at: datetime | None = None
    people: list[str] = Field(default_factory=list)
    url: str | None = None
    state: str | None = Field(default=None, description="The item's status as the app shows it")


class SignalFields(BaseModel):
    """Dotted paths inside one item to each signal field; the optional ones may be absent."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    due_at: str | None = None
    state: str | None = None
    people: str | None = None


class SignalSource(BaseModel):
    """Where one frozen step's result holds items that need attention, and how to read them."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, description="The id of the step whose result holds items")
    kind: str = Field(min_length=1, description="What each item is to the user")
    items_path: str = Field(
        default="", description="Dotted path from the step's result to the list; '' is the result"
    )
    fields: SignalFields


class LearnedSignal(BaseModel):
    """A signal as the learn run reports it, before the app name is stamped on."""

    external_id: str = Field(min_length=1)
    kind: str
    title: str = Field(min_length=1)
    why: str
    importance: SignalImportance
    due_at: datetime | None = None
    people: list[str] = Field(default_factory=list)
    url: str | None = None
    state: str | None = None


class ScoutReport(BaseModel):
    """The learn run's final answer: what it watches, how to repeat it, what it found today."""

    watching: str = Field(description="One line: what in this app can need the user")
    nothing_to_watch: bool = False
    steps: list[PlaybookHandoffStepInput] = Field(default_factory=list)
    sources: list[SignalSource] = Field(default_factory=list)
    signals: list[LearnedSignal] = Field(default_factory=list)


class ScoutStatus(StrEnum):
    """Whether a scout replays a frozen watch, or found nothing in its app worth watching."""

    WATCHING = "watching"
    NOTHING_TO_WATCH = "nothing_to_watch"


class ScoutDocument(UserScopedDocument):
    """One user's scout for one integration, keyed by (user_id, integration_id).

    tool_fingerprint is the integration's tool list when the scout learned; a different
    list means the frozen calls may no longer exist, so the scout learns again.
    """

    integration_id: str
    status: ScoutStatus
    tool_fingerprint: str
    playbook: PlaybookBody | None = None
    sources: list[SignalSource] = Field(default_factory=list)
    learned_at: datetime


class ScoutUpdate(BaseModel):
    """A scout is replaced whole on every learn, never patched."""

    model_config = ConfigDict(extra="forbid")


class ScoutOutcome(StrEnum):
    """How one scout's turn in a brief ended."""

    REPLAYED = "replayed"
    LEARNED = "learned"
    NOTHING_TO_WATCH = "nothing_to_watch"
    SKIPPED = "skipped"


class ScoutSkipReason(StrEnum):
    """Why a scout contributed nothing to this brief."""

    FAILED = "failed"
    BUDGET = "budget"


class ScoutResult(BaseModel):
    """One scout's contribution to a brief; a skipped scout says why and never stops the rest."""

    integration_id: str
    outcome: ScoutOutcome
    signals: list[Signal] = Field(default_factory=list)
    skip_reason: ScoutSkipReason | None = None
    error: str | None = None


class SignalMemoryDocument(UserScopedDocument):
    """What the brief remembers about one signal, keyed by (user_id, integration_id, external_id)."""

    integration_id: str
    external_id: str
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    times_shown: int = 0
    last_shown: datetime | None = None
    last_state: str | None = None


class SignalMemoryUpdate(BaseModel):
    """Signal memory is written by upserts, never patched by id."""

    model_config = ConfigDict(extra="forbid")


class RememberedSignal(BaseModel):
    """A signal the writer sees, with what the brief remembers about it."""

    signal: Signal
    memory: SignalMemoryDocument | None = None
    #: The state memory held before today's, when it moved.
    previous_state: str | None = None
