"""A stored brief as the API shows it: its card, its owner's view and the front page anyone else sees."""

from datetime import UTC, datetime

from app.constants.briefing import EditionVariant
from app.models.brief_document_models import BriefCardRecord, BriefingModel, EditionImage
from app.models.brief_payload_models import BriefingPayload
from app.models.brief_view_models import (
    BriefCard,
    BriefingView,
    EditionLeftOut,
    UncomposedItem,
)
from app.models.short_link_models import PublicBriefing, ShortLinkTargetType
from app.services.briefing.edition_image import edition_url
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.explorer_blocks import events_past_rows, left_out_items
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.services.briefing.editions.stamps import stamp_catalogue


async def edition_image(briefing: BriefingModel | BriefCardRecord) -> EditionImage | None:
    """Return the brief's edition as a surface loads it, by a URL signed now; None for a note."""
    edition = briefing.edition
    if edition is None:
        return None
    url = await edition_url(edition.key, EditionVariant.PNG, datetime.now(UTC))
    return EditionImage(image_url=url, fold=edition.fold, paper=edition.paper)


async def briefing_card(briefing: BriefingModel | BriefCardRecord) -> BriefCard:
    """Fold the brief to its card: name its edition and, for Air Mail, its stamp city, and count what needs the user.

    An edition is named as the editions settings list it; the weekly recap carries its kind instead.
    """
    record = BriefCardRecord.model_validate(briefing, from_attributes=True)
    payload = record.payload
    city = stamp_catalogue().get(payload.stamp_city) if payload.stamp_city else None
    return BriefCard(
        briefing_id=record.id,
        date=record.date,
        kind=record.kind,
        headline=payload.headline,
        edition=await edition_image(record),
        edition_name=explorer_family_names()[payload.template_family]
        if payload.template_family in DAILY_FAMILY_WEIGHTS
        else None,
        stamp_city_name=city.name if city else None,
        needs_you_count=sum(
            1 for section in payload.sections for item in section.items if item.kind.needs_you
        ),
    )


def edition_left_out(payload: BriefingPayload) -> EditionLeftOut:
    """List what the brief's edition left to its page, each pool item with the words for its state."""
    return EditionLeftOut(
        items=left_out_items(payload.blocks, payload.undrawn, payload.sections),
        events=events_past_rows(payload.calendar),
        uncomposed=[
            UncomposedItem(**item.model_dump(), state_label=item.kind.label)
            for item in payload.uncomposed
        ],
    )


async def briefing_view(briefing: BriefingModel) -> BriefingView:
    """Return the brief as its owner opens it: its card, the stored brief and what its edition left out."""
    return BriefingView(
        card=await briefing_card(briefing),
        payload=briefing.payload,
        delivered_channels=briefing.delivered_channels,
        opened_at=briefing.opened_at,
        created_at=briefing.created_at,
        left_out=edition_left_out(briefing.payload),
    )


def public_view(briefing: BriefingModel) -> PublicBriefing:
    """Project the brief for anyone but its owner: its front page, never an item or the item-bearing edition."""
    payload = briefing.payload
    return PublicBriefing(
        target_type=ShortLinkTargetType.BRIEFING,
        kind=briefing.kind,
        kicker=payload.kicker,
        date=payload.date,
        headline=payload.headline,
    )
