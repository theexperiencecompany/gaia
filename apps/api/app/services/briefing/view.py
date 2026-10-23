"""The archive's view of a stored brief, and the folded card its notification and chat message carry."""

from app.constants.briefing import NEEDS_YOU_SECTION_TITLE
from app.models.briefing_models import BriefingCardData, BriefingModel, BriefingView
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.services.briefing.editions.stamps import stamp_catalogue


def briefing_view(briefing: BriefingModel) -> BriefingView:
    """Name the brief's edition family and stamp city, and count what needs the user."""
    payload = briefing.payload
    family = payload.template_family
    city = stamp_catalogue().get(payload.stamp_city) if payload.stamp_city else None
    return BriefingView(
        **briefing.model_dump(),
        edition_name=explorer_family_names().get(family) if family else None,
        stamp_city_name=city.name if city else None,
        needs_you_count=sum(
            len(section.items)
            for section in payload.sections
            if section.title == NEEDS_YOU_SECTION_TITLE
        ),
    )


def briefing_card(view: BriefingView) -> BriefingCardData:
    """Fold the brief to the card its notification and its chat message carry."""
    return BriefingCardData(
        briefing_id=view.id,
        date=view.date,
        kind=view.kind,
        headline=view.payload.headline,
        edition_image_url=view.edition_image_url,
        edition_fold=view.edition_fold,
        edition_paper=view.edition_paper,
        edition_name=view.edition_name,
        stamp_city_name=view.stamp_city_name,
        needs_you_count=view.needs_you_count,
    )
