"""A stored brief as the API shows it: its card, the owner's view, the public view, the archive and the postmarks."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefingKind
from app.constants.notifications import NotificationKind
from app.models.brief_document_models import EditionImage
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefPoolItem,
)
from app.schemas.common import ResponseModel


class BriefCard(BaseModel):
    """A brief folded to its card: what the archive, a postmark, the notification and GAIA's chat message show."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    briefing_id: str
    date: str = Field(description="User-local YYYY-MM-DD.")
    kind: BriefingKind
    headline: str
    edition: EditionImage | None = Field(description="The edition image; None for a quiet note.")
    edition_name: str | None = Field(
        description="The daily edition family's name; None for the weekly recap and a quiet note."
    )
    stamp_city_name: str | None = Field(description="Air Mail only: the stamp city's name.")
    needs_you_count: int = Field(
        ge=0, description="Items in the brief's Needs you section, as its edition lists them."
    )


class BriefEditionNotification(BaseModel):
    """What a daily brief's or weekly recap's notification carries, for the in-app card and the email."""

    kind: Literal[NotificationKind.BRIEFING_DAILY, NotificationKind.BRIEFING_WEEKLY]
    brief_url: str = Field(description="The brief's heygaia.link.")
    card: BriefCard


class BriefNoteNotification(BaseModel):
    """What a quiet note's notification carries: its kind alone, as it has no edition and no link."""

    kind: Literal[NotificationKind.BRIEFING_NOTE]


#: A brief notification's metadata, told apart by its kind.
BriefNotificationMetadata = Annotated[
    BriefEditionNotification | BriefNoteNotification, Field(discriminator="kind")
]


class UncomposedItem(BriefPoolItem):
    """What GAIA read but the composition left out, with the words for where it stands."""

    state_label: str = Field(
        description="The item's state in a few words, as the brief page shows it."
    )


class EditionLeftOut(BaseModel):
    """What the rendered edition left to the brief's page, listed under it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[BriefingItem] = Field(
        description="The sections the edition could not draw, then the rows past its own."
    )
    events: list[BriefingEvent] = Field(description="The day's events past the rows it prints.")
    uncomposed: list[UncomposedItem]


class BriefingView(BaseModel):
    """A brief as its owner opens it: its card, the stored brief, and what its edition left out."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    card: BriefCard
    payload: BriefingPayload
    delivered_channels: list[str]
    opened_at: datetime | None
    created_at: datetime
    left_out: EditionLeftOut


class BriefingPublicView(BaseModel):
    """What anyone holding a brief's link sees: its edition and its front page, never its items or calendar.

    The owner sees the whole brief (BriefingView); a public viewer sees what the edition prints
    on its face, so no item text, calendar title or link beyond the image reaches them.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: BriefingKind
    kicker: str
    date: str
    headline: str
    lede: str
    caption: str
    mood: BriefingMood
    hue: int
    edition: EditionImage | None


class BriefingListResponse(BaseModel):
    """One page of the archive, newest first, and where the next page starts."""

    briefings: list[BriefCard]
    next_cursor: str | None = Field(
        description="Pass as before to read the next page; None on the last page."
    )


class Postmark(ResponseModel):
    """One collected Air Mail stamp: its city, where it sits, and the card of the brief it first came on.

    The card carries that brief's edition, so the page can ready the letter before the
    stamp is pressed without fetching the brief, which would mark it opened.
    """

    city_slug: str
    city: str
    country: str
    lat: float
    lng: float
    stamp_url: str
    card: BriefCard


class PostmarksResponse(ResponseModel):
    """The user's stamp collection, first arrival first."""

    total: int = Field(ge=0, description="How many city stamps can be collected.")
    postmarks: list[Postmark]
