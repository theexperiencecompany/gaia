"""Brief scouts: what a scout learned to watch, the signals it found, and what the brief remembers.

A scout answers one question per connected integration: what needs the user's attention
now or soon, read from the integration's current state. Its first (learn) run is a
read-only agent; the calls that run made are frozen as a playbook the daily brief replays
with no model, and each frozen result is read into signals by the paths the learn run named.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import NamedTuple, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.db.repositories.base import UserScopedDocument
from app.models.playbook_models import MAX_FOR_EACH_ITEMS, ForEachStep, PlaybookBody, ToolStep


class SignalImportance(StrEnum):
    """Whether a signal earns its own line in the brief, or a place in its app's group."""

    HIGH = "high"
    NORMAL = "normal"


class PeopleRole(StrEnum):
    """What the people an app names on an item are to it, when the app says."""

    AUTHOR = "author"
    ASSIGNEE = "assignee"
    REQUESTER = "requester"
    REVIEWER = "reviewer"
    RECIPIENT = "recipient"


class Signal(BaseModel):
    """One thing in one integration that needs the user's attention now or soon."""

    integration_id: str
    app: str = Field(description="The integration's display name")
    external_id: str = Field(min_length=1, description="The item's id inside the integration")
    kind: str = Field(description="What the item is to the user, in a few words of the app's terms")
    title: str = Field(min_length=1)
    why: str | None = Field(default=None, description="Why it needs attention now")
    importance: SignalImportance = SignalImportance.NORMAL
    due_at: datetime | None = None
    people: list[str] = Field(default_factory=list)
    #: What those people are to the item, when the app says; None when it does not.
    people_role: PeopleRole | None = None
    url: str | None = None
    state: str | None = Field(default=None, description="The item's status as the app shows it")
    #: The item's own figure (an invoice's total, a payout), when it carries one.
    amount: float | None = None
    #: What the amount counts, as the app's values read ("USD", "USD cents", "points").
    amount_unit: str | None = None
    #: The item's own words (a message, a comment), verbatim; None when it has none.
    text: str | None = None
    #: Who wrote those words, read from the same item; None when the app does not say.
    author: str | None = None
    #: When the item was created and last changed in the app; None when the app does not say.
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SignalFields(BaseModel):
    """Dotted paths inside one item to each signal field; the optional ones may be absent."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    due_at: str | None = None
    state: str | None = None
    people: str | None = None
    #: What the people at that path are to the item; None when the app does not say.
    people_role: PeopleRole | None = None
    amount: str | None = None
    text: str | None = None
    #: The path to who wrote the text; a quote is attributed only through it.
    author: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SignalSource(BaseModel):
    """Where one frozen step's result holds items that need attention, and how to read them."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, description="The id of the step whose result holds items")
    kind: str = Field(min_length=1, description="What each item is to the user")
    items_path: str = Field(
        default="", description="Dotted path from the step's result to the list; '' is the result"
    )
    fields: SignalFields
    amount_unit: str | None = Field(
        default=None, description="What each item's amount counts, as its values read"
    )


class LearnedSignal(BaseModel):
    """A signal as the learn run reports it, before the app name is stamped on."""

    external_id: str = Field(min_length=1)
    kind: str
    title: str = Field(min_length=1)
    why: str
    importance: SignalImportance
    due_at: datetime | None = None
    people: list[str] = Field(default_factory=list)
    people_role: PeopleRole | None = None
    url: str | None = None
    state: str | None = None
    amount: float | None = None
    amount_unit: str | None = None
    text: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScoutStep(BaseModel):
    """One call the learn run made and wants repeated, as its report writes it."""

    id: str = Field(default="", description="Name later steps and sources read this step by")
    tool: str = Field(min_length=1, description="Exact name of the tool this step calls")
    args: dict[str, JsonValue] = Field(
        default_factory=dict, description="The arguments the call ran with"
    )
    for_each: str | None = Field(
        default=None, description="A $steps path to a list; the call repeats once per element"
    )
    max_items: int | None = Field(
        default=None, ge=1, le=MAX_FOR_EACH_ITEMS, description="Most elements a for_each runs"
    )

    def to_step(self) -> ToolStep | ForEachStep:
        """Return the executed step this call replays as."""
        if self.for_each is None:
            return ToolStep(id=self.id, tool=self.tool, args=self.args)
        if self.max_items is None:
            raise ValueError(
                f"step {self.id or self.tool}: for_each needs max_items, at most "
                f"{MAX_FOR_EACH_ITEMS}, so the replay's cost is known before it runs"
            )
        return ForEachStep(
            id=self.id,
            tool=self.tool,
            args=self.args,
            for_each=self.for_each,
            max_items=self.max_items,
        )


class ScoutReport(BaseModel):
    """The learn run's final answer: what it watches, how to repeat it, what it found today."""

    watching: str = Field(description="One line: what in this app can need the user")
    criteria: str = Field(
        default="",
        description="How to tell which items need this user and which are important",
    )
    nothing_to_watch: bool = False
    steps: list[ScoutStep] = Field(default_factory=list)
    sources: list[SignalSource] = Field(default_factory=list)
    signals: list[LearnedSignal] = Field(default_factory=list)


class ScoutStatus(StrEnum):
    """Whether a scout replays a frozen watch, found nothing to watch, or waits to learn again."""

    WATCHING = "watching"
    NOTHING_TO_WATCH = "nothing_to_watch"
    LEARN_FAILED = "learn_failed"


class ScoutDocument(UserScopedDocument):
    """One user's scout for one integration, keyed by (user_id, integration_id).

    tool_fingerprint is the integration's tool list when the scout learned; a different
    list means the frozen calls may no longer exist, so the scout learns again. A failed
    learn waits until next_learn_at, unless the tools change: a working scout keeps its
    frozen calls meanwhile, any other is left LEARN_FAILED. failed_replays counts briefs in
    a row its app did not answer.
    """

    integration_id: str
    status: ScoutStatus
    tool_fingerprint: str
    playbook: PlaybookBody | None = None
    sources: list[SignalSource] = Field(default_factory=list)
    #: The learn run's criteria for which items matter; replayed items are judged by them.
    criteria: str = ""
    learned_at: datetime
    failed_learns: int = 0
    next_learn_at: datetime | None = None
    failed_replays: int = 0


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
    #: Learning failed recently; the scout waits out its backoff before learning again.
    BACKOFF = "backoff"
    #: The app did not answer the frozen calls; the scout keeps them for the next brief.
    SOURCE_FAILED = "source_failed"
    #: No tool of the integration is classified read-only, so a scout may call none.
    NO_READ_ONLY_TOOLS = "no_read_only_tools"
    #: The connection record names an integration that no longer exists.
    UNKNOWN_INTEGRATION = "unknown_integration"
    #: The app's sign-in expired or was revoked: only the user reconnecting it brings it back.
    SIGNED_OUT = "signed_out"


class ScoutResult(BaseModel):
    """One scout's contribution to a brief; a skipped scout says why and never stops the rest."""

    integration_id: str
    #: The integration's display name.
    app: str
    outcome: ScoutOutcome
    signals: list[Signal] = Field(default_factory=list)
    #: A replayed scout's criteria, which the brief's selection judge reads its rows by.
    criteria: str | None = None
    skip_reason: ScoutSkipReason | None = None
    error: str | None = None
    #: Whether the integration has tools that change things, so GAIA can act in it, not only read.
    can_write: bool = False


class SignalMemoryDocument(UserScopedDocument):
    """What the brief remembers about one signal, keyed by (user_id, integration_id, external_id)."""

    integration_id: str
    external_id: str
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    times_shown: int = 0
    last_shown: datetime | None = None
    last_state: str | None = None


class Sighted(Protocol):
    """Anything signal memory remembers: its key, and the state it was seen in."""

    @property
    def integration_id(self) -> str: ...
    @property
    def external_id(self) -> str: ...
    @property
    def state(self) -> str | None: ...


class Sighting(NamedTuple):
    """One brief item as signal memory keys it: GAIA's own work under GAIA's source."""

    integration_id: str
    external_id: str
    state: str | None


class SignalMemoryUpdate(BaseModel):
    """Signal memory is written by upserts, never patched by id."""

    model_config = ConfigDict(extra="forbid")


class RememberedSignal(BaseModel):
    """A signal the writer sees, with what the brief remembers about it."""

    signal: Signal
    memory: SignalMemoryDocument | None = None
    #: The state memory held before today's, when it moved.
    previous_state: str | None = None
