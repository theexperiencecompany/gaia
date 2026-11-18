"""A brief's payload: the structured brief the run emits and every channel renders, never markup.

One payload feeds every renderer (the edition, email, chat prose), so styling is the
renderers' and the payload only fills slots."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.briefing import (
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    HUE_MAX,
    MAX_BRIEF_CAPTION_CHARS,
    MAX_BRIEF_HEADLINE_CHARS,
    MAX_BRIEF_LEDE_CHARS,
    MAX_BRIEF_MESSAGE_CHARS,
    BriefAction,
    BriefForm,
    BriefOutcome,
    EditionFamily,
)
from app.models.brief_composition_models import BriefBlock
from app.models.brief_item_models import ItemState
from app.models.calendar_models import CalendarResponse
from app.models.scout_models import ScoutSkipReason


# ``mood`` keys the hero treatment (gradient + typographic emphasis) client-side.
# A closed set so renderers can switch on it; the prompt is held to these values.
class BriefingMood(StrEnum):
    """The hero treatment a brief is drawn with; the voice picks one of the daily moods."""

    CLEAR = "clear"
    PACKED = "packed"
    IDLE = "idle"
    WINBACK = "winback"
    WEEKLY = "weekly"


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
    kind: ItemState = ItemState.NOTE
    # heygaia.link to the item's artifact (canvas), a capability anyone holding it opens. The
    # chat message links to this instead of dumping the content; the dashboard
    # card renders it as a tappable item.
    link: str | None = None
    # How many tracked todos this one item stands for: todos sharing a parent or a
    # title are one thing to the user (todo_id is the first of them).
    count: int = Field(default=1, ge=1)
    #: The app the item came from ("GitHub", "Gmail", "GAIA"); None on legacy rows.
    app: str | None = None
    #: That app's integration id ("github"), or GAIA_SOURCE; the edition prints its mark.
    source: str | None = None
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
    """A group of items under the heading GAIA gave it, numbered in reading order."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    numeral: str
    title: str
    items: list[BriefingItem] = Field(default_factory=list)


class BriefPoolItem(BaseModel):
    """A pool item the composition left out, in its source's own words, for the full brief page."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    title: str = Field(min_length=1)
    detail: str | None = None
    kind: ItemState
    app: str
    url: str | None = None
    todo_id: str | None = None


#: How a BriefingEvent stores a time on the user's clock: "14:30".
EVENT_TIME_FORMAT = "%H:%M"


class BriefingEvent(BaseModel):
    """One calendar event on the user's own clock, read from their calendar."""

    date: str  # user-local YYYY-MM-DD
    start: str | None = None  # user-local "HH:MM"; None for an all-day event
    #: user-local "HH:MM" it ends at, when timed and ending the day it starts.
    end: str | None = None
    title: str
    location: str | None = None
    #: The calendar it is on, as its owner titled it.
    calendar: str | None = None
    response: CalendarResponse = CalendarResponse.OWN
    #: Who organized it, when that is someone else.
    organizer: str | None = None
    #: How many others are invited.
    guests: int = 0


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
    """The real week behind the weekly recap: Monday-to-Sunday completions and the
    calendar ahead. Every field is counted or read, never estimated."""

    days: list[BriefingWeekDay] = Field(min_length=7, max_length=7)
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

    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    kicker: str
    date: str
    headline: str
    lede: str
    stats: list[BriefingStat] = Field(default_factory=list)
    sections: list[BriefingSection] = Field(default_factory=list)
    mood: BriefingMood
    caption: str
    hue: int = Field(default=0, ge=0, le=HUE_MAX)
    template_family: EditionFamily | None = Field(
        description=(
            "The edition template family this brief was drawn in, persisted so the archive "
            "re-renders identically forever; None for a quiet note, which is drawn in none."
        ),
    )
    stamp_city: str | None = Field(
        default=None,
        description=(
            "Air Mail editions only: the city stamp (a stamps/cities.json slug) "
            "this brief carried. The Postmarks page reads it."
        ),
    )
    artwork_id: str | None = Field(
        default=None,
        description=(
            "Exhibition, Broadsheet and Almanac editions only: the painting (an "
            "artworks/artworks.json slug) this brief hangs, so a re-render hangs it again."
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
    #: An edition, or the plain note a quiet day sends instead of one.
    form: BriefForm = BriefForm.EDITION
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
    blocks: list[BriefBlock] = Field(
        default_factory=list,
        description=(
            "The brief as GAIA composed it, in reading order: each lead or items block "
            "names its section; charts, quotes, progress and notes carry their data. "
            "Empty on legacy rows."
        ),
    )
    uncomposed: list[BriefPoolItem] = Field(
        default_factory=list,
        description="Everything the brief read that the composition left out, for its full page.",
    )
    undrawn: list[BriefBlock] = Field(
        default_factory=list,
        description=(
            "Composed blocks the drawn edition cannot draw in its idiom (a chart on the Menu), "
            "moved out of blocks onto the brief's full page."
        ),
    )
