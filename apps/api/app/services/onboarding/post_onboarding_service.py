"""Personalization persistence for the Gmail pipeline."""

from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import BioStatus
from shared.py.wide_events import log


async def save_personalization_data(
    user_id: str,
    house: str,
    personality_phrase: str,
    user_bio: str,
    bio_status: BioStatus,
    account_number: int,
    member_since: str,
    overlay_color: str,
    overlay_opacity: int,
) -> None:
    """Save the generated holo-card bundle to the user document."""
    try:
        await user_repository.save_personalization(
            user_id,
            house=house,
            personality_phrase=personality_phrase,
            user_bio=user_bio,
            bio_status=bio_status,
            account_number=account_number,
            member_since=member_since,
            overlay_color=overlay_color,
            overlay_opacity=overlay_opacity,
        )
        log.info(f"{LogTag.ONBOARDING} Saved personalization data for user", user_id=user_id)

    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error saving personalization data",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            exc_info=True,
        )
