"""Briefing artifact models.

The briefing run emits a Pydantic-validated ``BriefingPayload`` — never markup.
One payload feeds every renderer (dashboard OpenUI card, email, Telegram prose),
so styling is entirely client-owned and the payload only fills slots. Payloads
are persisted in the ``briefings`` collection, one per user/date/kind.
"""

from datetime import UTC, datetime
from typing import Literal, Self
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.briefing import (
    ACTION_SECTIONS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEFING_KIND_DAILY,
    DAILY_BRIEFING_HOUR,
    HUE_MAX,
    MAX_BRIEF_CAPTION_CHARS,
    MAX_BRIEF_HEADLINE_CHARS,
    MAX_BRIEF_LEDE_CHARS,
    MAX_BRIEF_MESSAGE_CHARS,
    BriefAction,
    BriefingFrequency,
    BriefOutcome,
    SectionKey,
)
from app.db.repositories.base import UserScopedDocument
from app.models.scout_models import ScoutSkipReason
from app.schemas.common import ResponseModel

BriefingKind = Literal["daily", "weekly"]

# ``mood`` keys the hero treatment (gradient + typographic emphasis) client-side.
# A closed set so renderers can switch on it; the prompt is held to these values.
BriefingMood = Literal["clear", "packed", "idle", "winback", "weekly"]

# ``kind`` on a section item tags how the renderer treats it (a GAIA action, a
# user ask, a look-back note, work that failed, a plain highlight). The kind is
# the item's state; ``text`` is only its title, so no renderer repeats the state.
BriefingItemKind = Literal["gaia", "you", "lookback", "failed", "note"]

# The state each kind reads as where plain text is all there is (the voice facts).
BRIEFING_ITEM_STATES: dict[BriefingItemKind, str] = {
    "you": "Waiting on you",
    "gaia": "In progress",
    "lookback": "Done",
    "failed": "Failed",
    "note": "Note",
}
# The kinds that wait on the reader: their own asks and work that failed.
NEEDS_YOU_ITEM_KINDS: frozenset[BriefingItemKind] = frozenset({"you", "failed"})


class BriefingSchedule(BaseModel):
    """When the user wants their briefs: how often, and the daily brief's local hour."""

    frequency: BriefingFrequency = BriefingFrequency.DAILY
    hour: int = Field(default=DAILY_BRIEFING_HOUR, ge=0, le=23)


class BriefingStat(BaseModel):
    """One tuple in the stat row (e.g. value="12" label="drafts staged")."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    value: str
    label: str
    delta: str | None = None


class BriefingItem(BaseModel):
    """A single line inside a section, optionally bound to a todo.

    It either asks something of the reader (action) or reports where a thing got to
    (outcome), never both, under a short title and at most one detail line.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The item's title: a noun phrase, never a sentence.
    text: str = Field(min_length=1, max_length=BRIEF_ITEM_TITLE_MAX_CHARS)
    action: BriefAction | None = None
    outcome: BriefOutcome | None = None
    detail: str | None = Field(default=None, min_length=1, max_length=BRIEF_ITEM_DETAIL_MAX_CHARS)
    todo_id: str | None = None
    kind: BriefingItemKind = "note"
    # heygaia.link handle for the item's artifact (canvas), viewer-scoped. The
    # chat message links to this instead of dumping the content; the dashboard
    # card renders it as a tappable item.
    link: str | None = None
    # How many tracked todos this one item stands for: todos sharing a parent or a
    # title are one thing to the user (todo_id is the first of them).
    count: int = Field(default=1, ge=1)
    #: The app the item came from ("GitHub", "Gmail", "GAIA"); None on legacy rows.
    app: str | None = None
    #: A deep link into that app, when it gave one.
    url: str | None = None
    people: list[str] = Field(default_factory=list)
    #: What GAIA offers to do about the item (the lead's "Let's do it"); None when nothing.
    offer: str | None = None

    @model_validator(mode="after")
    def _one_action_or_outcome(self) -> Self:
        if (self.action is None) == (self.outcome is None):
            raise ValueError(f"item {self.text!r} needs exactly one of action or outcome")
        return self


class BriefingSection(BaseModel):
    """A Roman-numeraled section of the briefing."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    numeral: str
    title: str
    items: list[BriefingItem] = Field(default_factory=list)
    #: What the section holds; None on legacy rows and on the model-written weekly recap.
    key: SectionKey | None = None
    #: Items chosen for the section that its cap left out, for "+N more in the full brief".
    more: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _items_fit_the_section(self) -> Self:
        if self.key is None:
            return self
        asks = self.key in ACTION_SECTIONS
        misfit = [i.text for i in self.items if (i.action is not None) != asks]
        if misfit:
            needed = "an action" if asks else "an outcome"
            raise ValueError(f"{self.key.value} items need {needed}: {misfit}")
        return self


class BriefingEvent(BaseModel):
    """One calendar event on the user's own clock, read from their calendar."""

    date: str  # user-local YYYY-MM-DD
    start: str | None = None  # user-local "HH:MM"; None for an all-day event
    title: str
    location: str | None = None


class UnreadSource(BaseModel):
    """A connected app the brief could not read this time, and why."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    app: str
    reason: ScoutSkipReason


class BriefingTallies(BaseModel):
    """Completed-todo counts behind the brief, computed from the todos store —
    never parsed back out of stat labels, so every renderer agrees with them."""

    done_by_you: int = Field(ge=0)
    done_by_gaia: int = Field(ge=0)


class BriefingWeekDay(BaseModel):
    """Todos completed on one day of the week, by owner."""

    you: int = Field(ge=0)
    gaia: int = Field(ge=0)


class BriefingWeek(BaseModel):
    """The real week the weekly edition draws: Monday-to-Sunday completions,
    what shipped, what GAIA handled, and the calendar ahead. Every field is
    counted or read, never estimated."""

    days: list[BriefingWeekDay] = Field(min_length=7, max_length=7)
    shipped: list[str] = Field(default_factory=list)
    handled: list[str] = Field(default_factory=list)
    ahead: list[BriefingEvent] = Field(default_factory=list)


class NewStamp(BaseModel):
    """A city stamp the user collected for the first time with this brief."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    city: str
    country: str
    collected: int = Field(ge=1, description="Stamps collected, this one included.")
    total: int = Field(ge=1, description="How many city stamps can be collected.")


class BriefVoice(BaseModel):
    """The prose a brief's model writes over code-built facts, as written or as rendered."""

    headline: str = Field(max_length=MAX_BRIEF_HEADLINE_CHARS)
    lede: str = Field(max_length=MAX_BRIEF_LEDE_CHARS)
    caption: str = Field(max_length=MAX_BRIEF_CAPTION_CHARS)
    mood: BriefingMood
    message: str = Field(min_length=1, max_length=MAX_BRIEF_MESSAGE_CHARS)


class BriefingPayload(BaseModel):
    """The structured briefing the run emits and every channel renders."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kicker: str
    date: str
    headline: str
    lede: str
    stats: list[BriefingStat] = Field(default_factory=list)
    sections: list[BriefingSection] = Field(default_factory=list)
    mood: BriefingMood
    caption: str
    hue: int = Field(default=0, ge=0, le=HUE_MAX)
    template_family: str = Field(
        description=(
            "The edition template family this brief was drawn in. Persisted so "
            "the archive re-renders identically forever."
        ),
    )
    stamp_city: str | None = Field(
        default=None,
        description=(
            "Air Mail editions only: the city stamp (a stamps/cities.json slug) "
            "this brief carried. The Postmarks page reads it."
        ),
    )
    new_stamp: NewStamp | None = Field(
        default=None,
        description="Set when this brief's stamp is one the user had not collected before.",
    )
    recipient_name: str | None = Field(
        default=None,
        description=(
            "The user's name as the edition addresses them (an envelope, a memo's "
            "TO: line); None when unknown or on legacy rows."
        ),
    )
    generated_at: str | None = Field(
        default=None, description='User-local generation time, e.g. "6:02 AM".'
    )
    link: str | None = Field(
        default=None,
        description=(
            "The brief's link, set before its edition renders: its heygaia.link, or its "
            "page URL when minting failed. The edition's QR and barcodes encode it; "
            "None on legacy rows."
        ),
    )
    calendar: list[BriefingEvent] = Field(
        default_factory=list, description="Today's calendar events, in start order."
    )
    tallies: BriefingTallies | None = None
    week: BriefingWeek | None = None
    sources_read: list[str] = Field(
        default_factory=list, description="The apps the brief read, by display name."
    )
    sources_unavailable: list[UnreadSource] = Field(default_factory=list)
    message: str | None = Field(
        default=None,
        description=(
            "The brief as the user reads it: the text GAIA writes over the code-built "
            "facts, sent after the edition image in chat, under it in the email and on "
            "the brief's page. None on legacy rows."
        ),
    )


def new_briefing_id() -> str:
    """Return a fresh brief id."""
    return f"brief_{uuid.uuid4().hex[:12]}"


class EditionRender(BaseModel):
    """Where a brief's hosted edition render lives, and where its letter sits on it."""

    model_config = ConfigDict(frozen=True)

    image_url: str
    fold: float | None = None
    paper: list[float] | None = None


class BriefingModel(UserScopedDocument):
    """Persisted briefing document (``briefings`` collection).

    Doubles as the repository's document model (``BriefingsRepository`` in
    ``app/db/repositories/briefings.py``) — one canonical model for the
    persisted shape and every consumer (endpoints, ``BriefingListResponse``,
    the archive/dashboard reads). Identity is the string business key ``id``,
    persisted as Mongo's ``_id`` (``uses_object_id=False``).
    """

    model_config = ConfigDict(
        extra="ignore", from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: str = Field(default_factory=new_briefing_id)
    date: str  # user-local YYYY-MM-DD
    kind: BriefingKind = BRIEFING_KIND_DAILY
    payload: BriefingPayload
    delivered_channels: list[str] = Field(default_factory=list)
    #: The hosted full edition render: the in-app page, the email and the short link show it.
    edition_image_url: str | None = None
    #: Share of the edition image's height where its letter folds, read from the template's marker.
    edition_fold: float | None = None
    #: The paper's box on its desk as [left, top, right, bottom] shares of the edition image.
    edition_paper: list[float] | None = None
    opened_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class BriefingUpdate(BaseModel):
    """Typed ``$set`` fields for a briefing. Every real write (payload swap,
    delivered-channels list, the idempotent opened-at stamp) goes through its
    own named repository method with its own filter guard, so this exists only
    to satisfy the repository base's typed-update-model contract."""

    model_config = ConfigDict(extra="forbid")

    payload: BriefingPayload | None = None
    delivered_channels: list[str] | None = None
    opened_at: datetime | None = None


class BriefingView(BriefingModel):
    """A brief as the archive and its folded card show it: the stored brief plus its edition's names."""

    edition_name: str | None = Field(
        description="Air Mail only: the family's name; None for every other family."
    )
    stamp_city_name: str | None = Field(description="Air Mail only: the stamp city's name.")
    needs_you_count: int = Field(
        ge=0, description="Items in the brief's Needs you section, as its edition lists them."
    )


class BriefingCardData(BaseModel):
    """A brief folded to its card: what the in-app notification and GAIA's chat message carry."""

    briefing_id: str
    date: str
    kind: BriefingKind
    headline: str
    edition_image_url: str | None
    edition_fold: float | None
    edition_paper: list[float] | None
    edition_name: str | None
    stamp_city_name: str | None
    needs_you_count: int = Field(ge=0)


class BriefingListResponse(BaseModel):
    """Archive response shape (frontend is coded against this)."""

    briefings: list[BriefingView]


class Postmark(ResponseModel):
    """One collected Air Mail stamp: its city, where it sits, and the brief it came on."""

    city_slug: str
    city: str
    country: str
    lat: float
    lng: float
    stamp_url: str
    date: str = Field(description="User-local YYYY-MM-DD the stamp first arrived.")
    briefing_id: str = Field(description="The brief that first carried the stamp.")


class PostmarksResponse(ResponseModel):
    """The user's stamp collection, first arrival first."""

    total: int = Field(ge=0, description="How many city stamps can be collected.")
    postmarks: list[Postmark]
