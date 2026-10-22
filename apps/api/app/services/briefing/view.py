"""The archive's view of a stored brief: its edition's display names and its Needs you count."""

from app.constants.briefing import NEEDS_YOU_SECTION_TITLE
from app.models.briefing_models import BriefingModel, BriefingView
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
