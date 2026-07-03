"""Briefing artifact models.

The briefing run emits a Pydantic-validated ``BriefingPayload`` — never markup.
One payload feeds every renderer (dashboard OpenUI card, email, Telegram prose),
so styling is entirely client-owned and the payload only fills slots. Payloads
are persisted in the ``briefings`` collection, one per user/date/kind.
"""

from datetime import UTC, datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BRIEFING_KIND_DAILY, HUE_MAX

BriefingKind = Literal["daily", "weekly"]

# ``mood`` keys the hero treatment (gradient + typographic emphasis) client-side.
# A closed set so renderers can switch on it; the prompt is held to these values.
BriefingMood = Literal["clear", "packed", "idle", "winback", "weekly"]

# ``kind`` on a section item tags how the renderer treats it (a GAIA action, a
# user ask, a proposal awaiting approval, a look-back note, a plain highlight).
BriefingItemKind = Literal["gaia", "you", "proposal", "lookback", "note"]


class BriefingStat(BaseModel):
    """One tuple in the stat row (e.g. value="12" label="drafts staged")."""

    value: str
    label: str
    delta: str | None = None


class BriefingItem(BaseModel):
    """A single line inside a section, optionally bound to a todo."""

    text: str
    todo_id: str | None = None
    kind: BriefingItemKind = "note"


class BriefingSection(BaseModel):
    """A Roman-numeraled section of the briefing."""

    numeral: str
    title: str
    items: list[BriefingItem] = Field(default_factory=list)


class BriefingPayload(BaseModel):
    """The structured briefing the run emits and every channel renders."""

    kicker: str
    date: str
    headline: str
    lede: str
    stats: list[BriefingStat] = Field(default_factory=list)
    sections: list[BriefingSection] = Field(default_factory=list)
    mood: BriefingMood
    caption: str
    hue: int = Field(default=0, ge=0, le=HUE_MAX)


class BriefingModel(BaseModel):
    """Persisted briefing document (``briefings`` collection)."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: f"brief_{uuid.uuid4().hex[:12]}")
    user_id: str
    date: str  # user-local YYYY-MM-DD
    kind: BriefingKind = BRIEFING_KIND_DAILY
    payload: BriefingPayload
    delivered_channels: list[str] = Field(default_factory=list)
    opened_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BriefingListResponse(BaseModel):
    """Archive response shape (frontend is coded against this)."""

    briefings: list[BriefingModel]
