"""A stored brief as the API shows it: the owner's view, the public view, its card, the archive and the postmarks."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefingKind
from app.models.brief_document_models import EditionImage
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.schemas.common import ResponseModel


class BriefingView(BaseModel):
    """A brief as the archive and its folded card show it: the stored brief plus its edition's names."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    date: str = Field(description="User-local YYYY-MM-DD.")
    kind: BriefingKind
    payload: BriefingPayload
    delivered_channels: list[str]
    opened_at: datetime | None
    created_at: datetime
    edition: EditionImage | None = Field(description="The edition image; None for a quiet note.")

    edition_name: str | None = Field(
        description="The daily edition family's name; None for the weekly recap and a quiet note."
    )
    stamp_city_name: str | None = Field(description="Air Mail only: the stamp city's name.")
    needs_you_count: int = Field(
        ge=0, description="Items in the brief's Needs you section, as its edition lists them."
    )


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


class BriefingCardData(BaseModel):
    """A brief folded to its card: what the in-app notification and GAIA's chat message carry."""

    briefing_id: str
    date: str
    kind: BriefingKind
    headline: str
    edition: EditionImage | None
    edition_name: str | None
    stamp_city_name: str | None
    needs_you_count: int = Field(ge=0)


class BriefingListResponse(BaseModel):
    """One page of the archive, newest first, and where the next page starts."""

    briefings: list[BriefingView]
    next_cursor: str | None = Field(
        description="Pass as before to read the next page; None on the last page."
    )


class Postmark(ResponseModel):
    """One collected Air Mail stamp: its city, where it sits, and the brief it came on.

    It carries that brief's edition, so the page can ready the letter before the
    stamp is pressed without fetching the brief, which would mark it opened.
    """

    city_slug: str
    city: str
    country: str
    lat: float
    lng: float
    stamp_url: str
    date: str = Field(description="User-local YYYY-MM-DD the stamp first arrived.")
    briefing_id: str = Field(description="The brief that first carried the stamp.")
    edition: EditionImage | None = Field(description="That brief's edition image.")


class PostmarksResponse(ResponseModel):
    """The user's stamp collection, first arrival first."""

    total: int = Field(ge=0, description="How many city stamps can be collected.")
    postmarks: list[Postmark]
