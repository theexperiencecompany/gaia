"""A stored brief: its document in the briefings collection, its edition render and how far its delivery got."""

from datetime import UTC, datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefingKind, EditionFamily
from app.constants.notifications import NotificationKind
from app.db.repositories.base import UserScopedDocument
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import BriefingPayload
from app.models.briefing_state_models import BagDraw
from app.models.scout_models import Sighting


def new_briefing_id() -> str:
    """Return a fresh brief id."""
    return f"brief_{uuid.uuid4().hex[:12]}"


class EditionLayout(BaseModel):
    """Where an edition's letter folds and where its paper lies on it."""

    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    fold: float | None = Field(
        default=None, description="Share of the edition's height where its letter folds."
    )
    paper: list[float] | None = Field(
        default=None,
        description="The paper's box on its desk as [left, top, right, bottom] shares; None when it fills the image.",
    )


class EditionRender(EditionLayout):
    """A brief's stored edition: the opaque key its image blobs are stored under, and its layout."""

    key: str


class EditionImage(EditionLayout):
    """A brief's edition as a surface loads it: its signed URL, its fold and its paper."""

    image_url: str = Field(description="A signed URL that loads the edition image for a year.")


class DeliveryStep(StrEnum):
    """One way a brief goes out; each is recorded on the brief the moment it succeeds."""

    #: The notification orchestrator: in-app, plus email when wanted.
    NOTIFICATION = "notification"
    #: GAIA's message in the user's Briefings conversation.
    CONVERSATION = "conversation"
    #: The edition posted into the user's chat app.
    CHAT = "chat"


class BriefSettlement(BaseModel):
    """What the brief's run owes the reader's briefing state once the brief went out."""

    #: The hold an existing user's first brief waited under for a goal is cleared.
    clears_bootstrap: bool = False
    #: The brief asked about the user's goal, or for one.
    asked_goal: bool = False
    #: The brief said the idle ladder's goodbye: the loop goes dormant.
    goes_dormant: bool = False


class BriefDelivery(BaseModel):
    """How a stored brief goes out and how far it got, so a retried run finishes it instead of resending it.

    The step that completes its delivery also settles what its run owes: the held results it
    carries, the bag draws it spent, the items it showed and the reader's state.
    """

    #: Whether it goes beyond in-app: email when wanted, and the chat app.
    push: bool
    notification_kind: NotificationKind
    #: The held results it carries, consumed in the step that completes its delivery.
    held_ids: list[str] = Field(default_factory=list)
    #: The edition's bag draws, spent only by a pushed brief.
    draws: list[BagDraw] = Field(default_factory=list)
    #: The placed items as signal memory keys them, marked shown.
    shown: list[Sighting] = Field(default_factory=list)
    settlement: BriefSettlement = Field(default_factory=BriefSettlement)
    done: list[DeliveryStep] = Field(default_factory=list)
    completed_at: datetime | None = None


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
    kind: BriefingKind = BriefingKind.DAILY
    payload: BriefingPayload
    delivered_channels: list[str] = Field(default_factory=list)
    #: The stored edition render; None for a quiet day's note, which has none.
    edition: EditionRender | None = None
    #: None only on a brief whose delivery was never planned (a seed, a legacy row).
    delivery: BriefDelivery | None = None
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


class _CardItem(BaseModel):
    kind: ItemState = ItemState.NOTE


class _CardSection(BaseModel):
    items: list[_CardItem] = Field(default_factory=list)


class BriefCardPayload(BaseModel):
    """The payload fields a brief's card reads: its headline, edition, stamp and item states."""

    headline: str
    template_family: EditionFamily | None = None
    stamp_city: str | None = None
    sections: list[_CardSection] = Field(default_factory=list)


class BriefCardRecord(BaseModel):
    """A stored brief read for its card alone, never its whole payload: what the archive and Postmarks list."""

    id: str
    date: str
    kind: BriefingKind
    edition: EditionRender | None = None
    payload: BriefCardPayload
