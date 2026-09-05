"""Briefing artifact models.

The briefing run emits a Pydantic-validated ``BriefingPayload`` — never markup.
One payload feeds every renderer (dashboard OpenUI card, email, Telegram prose),
so styling is entirely client-owned and the payload only fills slots. Payloads
are persisted in the ``briefings`` collection, one per user/date/kind.
"""

from datetime import UTC, datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.briefing import BRIEFING_KIND_DAILY, HUE_MAX
from app.constants.notifications import DEFAULT_CHAT_CHANNEL_PRIORITY
from app.db.repositories.base import UserScopedDocument

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
    # heygaia.link handle for the item's artifact (canvas), viewer-scoped. The
    # chat message links to this instead of dumping the content; the dashboard
    # card renders it as a tappable item.
    link: str | None = None


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
    template_family: str | None = Field(
        default=None,
        description=(
            "Weekly editions only: the edition template family this payload was "
            "assigned by the shuffled-cycle rotation. Persisted so the archive "
            "re-renders identically forever; None on daily briefs and legacy rows."
        ),
    )
    message: str | None = Field(
        default=None,
        description=(
            "Casual texting-voice rendering of the brief for chat platforms "
            "(Telegram/WhatsApp/etc). The editorial fields above are for the "
            "dashboard card and email; this is what GAIA 'texts' the user. "
            "Derived from `bubbles` (joined) for single-string consumers."
        ),
    )
    bubbles: list[str] = Field(
        default_factory=list,
        description=(
            "One chat bubble per goal — each led by the goal, concrete details "
            "inline, a heygaia.link only when the artifact is large/actionable. "
            "Delivered as separate messages so each goal reads on its own."
        ),
    )


class BriefingModel(UserScopedDocument):
    """Persisted briefing document (``briefings`` collection).

    Doubles as the repository's document model (``BriefingsRepository`` in
    ``app/db/repositories/briefings.py``) — one canonical model for the
    persisted shape and every consumer (endpoints, ``BriefingListResponse``,
    the archive/dashboard reads). Identity is the string business key ``id``,
    persisted as Mongo's ``_id`` (``uses_object_id=False``).
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str = Field(default_factory=lambda: f"brief_{uuid.uuid4().hex[:12]}")
    date: str  # user-local YYYY-MM-DD
    kind: BriefingKind = BRIEFING_KIND_DAILY
    payload: BriefingPayload
    delivered_channels: list[str] = Field(default_factory=list)
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


class AwardDocument(UserScopedDocument):
    """One earned badge (``awards`` collection). ``(user_id, key)`` is unique —
    each badge is earnable once (``AwardsRepository`` in
    ``app/db/repositories/awards.py``). ``created_at`` (base-stamped on insert)
    IS the earned timestamp — no separate field for the same moment."""

    key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class AwardUpdate(BaseModel):
    """Awards are immutable once earned — no field is ever updated in place.
    Exists only to satisfy the repository base's typed-update-model contract."""

    model_config = ConfigDict(extra="forbid")


class BriefingListResponse(BaseModel):
    """Archive response shape (frontend is coded against this)."""

    briefings: list[BriefingModel]


class ChannelPriorityResponse(BaseModel):
    """The user's briefing chat-channel priority order (settings UI reads this)."""

    chat_channel_priority: list[str]


class ChannelPriorityUpdate(BaseModel):
    """A non-empty, duplicate-free ordered subset of the four chat platforms."""

    chat_channel_priority: list[str] = Field(min_length=1)

    @field_validator("chat_channel_priority")
    @classmethod
    def _validate_platforms(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("chat_channel_priority must not contain duplicates")
        unknown = [p for p in value if p not in DEFAULT_CHAT_CHANNEL_PRIORITY]
        if unknown:
            raise ValueError(f"unknown chat platform(s): {', '.join(unknown)}")
        return value
