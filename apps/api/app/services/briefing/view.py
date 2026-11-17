"""The archive's view of a stored brief, and the folded card its notification and chat message carry."""

from datetime import UTC, datetime

from app.constants.briefing import EditionVariant
from app.models.briefing_models import (
    NEEDS_YOU_ITEM_KINDS,
    BriefingCardData,
    BriefingModel,
    BriefingPublicView,
    BriefingView,
    EditionImage,
)
from app.services.briefing.edition_image import edition_url
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.services.briefing.editions.stamps import stamp_catalogue


async def edition_image(briefing: BriefingModel) -> EditionImage | None:
    """Return the brief's edition as a surface loads it, by a URL signed now; None for a note."""
    edition = briefing.edition
    if edition is None:
        return None
    url = await edition_url(edition.key, EditionVariant.PNG, datetime.now(UTC))
    return EditionImage(image_url=url, fold=edition.fold, paper=edition.paper)


async def briefing_view(briefing: BriefingModel) -> BriefingView:
    """Name the brief's edition and, for Air Mail, its stamp city, and count what needs the user.

    An edition is named as the editions settings list it; the weekly recap carries its kind instead.
    """
    payload = briefing.payload
    city = stamp_catalogue().get(payload.stamp_city) if payload.stamp_city else None
    return BriefingView(
        id=briefing.id,
        date=briefing.date,
        kind=briefing.kind,
        payload=briefing.payload,
        delivered_channels=briefing.delivered_channels,
        opened_at=briefing.opened_at,
        created_at=briefing.created_at,
        edition=await edition_image(briefing),
        edition_name=explorer_family_names()[payload.template_family]
        if payload.template_family in DAILY_FAMILY_WEIGHTS
        else None,
        stamp_city_name=city.name if city else None,
        needs_you_count=sum(
            1
            for section in payload.sections
            for item in section.items
            if item.kind in NEEDS_YOU_ITEM_KINDS
        ),
    )


def briefing_card(view: BriefingView) -> BriefingCardData:
    """Fold the brief to the card its notification and its chat message carry."""
    return BriefingCardData(
        briefing_id=view.id,
        date=view.date,
        kind=view.kind,
        headline=view.payload.headline,
        edition=view.edition,
        edition_name=view.edition_name,
        stamp_city_name=view.stamp_city_name,
        needs_you_count=view.needs_you_count,
    )


async def public_view(briefing: BriefingModel) -> BriefingPublicView:
    """Project the brief for a viewer who is not its owner: the edition and its front page alone."""
    payload = briefing.payload
    return BriefingPublicView(
        kind=briefing.kind,
        kicker=payload.kicker,
        date=payload.date,
        headline=payload.headline,
        lede=payload.lede,
        caption=payload.caption,
        mood=payload.mood,
        hue=payload.hue,
        edition=await edition_image(briefing),
    )
