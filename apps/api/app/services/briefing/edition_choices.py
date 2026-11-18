"""Which daily edition families the user keeps in their brief's rotation, and which they favour."""

from collections.abc import Mapping

from app.constants.briefing import EditionChoice
from app.db.repositories.users import user_repository
from app.models.brief_settings_models import BriefingEdition, BriefingEditions
from app.services.analytics_service import capture
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.utils.errors import create_error
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsBriefingEditionsUpdated
from shared.py.wide_events import log


def briefing_editions(choices: Mapping[str, EditionChoice]) -> BriefingEditions:
    """Return every daily edition family, by name, with where the user put it."""
    names = explorer_family_names()
    return BriefingEditions(
        editions=sorted(
            (
                BriefingEdition(
                    family=family,
                    name=names[family],
                    choice=choices.get(family, EditionChoice.ON),
                )
                for family in DAILY_FAMILY_WEIGHTS
            ),
            key=lambda edition: edition.name,
        )
    )


async def set_edition_choices(
    user_id: str, choices: Mapping[str, EditionChoice]
) -> BriefingEditions:
    """Store where the user put each daily edition family; at least one must stay on.

    Raises an AppError (422) for a family that is not a daily edition, or when every one is off.
    """
    unknown = sorted(set(choices) - set(DAILY_FAMILY_WEIGHTS))
    if unknown:
        raise create_error(
            message=f"Not a daily edition: {', '.join(unknown)}",
            why="Only the daily edition families can be turned off or favourited",
            fix="Choose from the editions GET /notifications/preferences/briefing-editions lists",
            status_code=422,
        )
    stored = {family: choice for family, choice in choices.items() if choice != EditionChoice.ON}
    if all(stored.get(family) == EditionChoice.OFF for family in DAILY_FAMILY_WEIGHTS):
        raise create_error(
            message="Keep at least one edition on",
            why="Every brief is drawn from the editions you keep on",
            fix="Turn one edition back on",
            status_code=422,
        )
    await user_repository.set_briefing_editions(user_id, stored)
    off = sum(1 for choice in stored.values() if choice == EditionChoice.OFF)
    favourites = len(stored) - off
    log.audit("briefing editions updated", actor=user_id, off=off, favourites=favourites)
    capture(
        UserId(user_id),
        SettingsBriefingEditionsUpdated(
            editions_off=off,
            editions_favourited=favourites,
            editions_total=len(DAILY_FAMILY_WEIGHTS),
        ),
    )
    return briefing_editions(stored)
