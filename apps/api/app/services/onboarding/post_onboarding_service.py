"""Post-onboarding personalization service."""

from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import BioStatus
from app.utils.seeding_utils import seed_onboarding_todo
from shared.py.wide_events import log


async def save_personalization_data(
    user_id: str,
    house: str,
    personality_phrase: str,
    user_bio: str,
    bio_status: BioStatus,
    workflow_ids: list[str],
    account_number: int,
    member_since: str,
    overlay_color: str,
    overlay_opacity: int,
) -> None:
    """
    Save personalization data to user document.

    Args:
        user_id: User identifier
        house: Assigned house
        personality_phrase: Generated phrase
        user_bio: Generated bio
        bio_status: Status of bio generation
        workflow_ids: Suggested workflow IDs
        account_number: User's account number
        member_since: Member since date
        overlay_color: Generated overlay color or gradient
        overlay_opacity: Opacity percentage
    """
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
            workflow_ids=workflow_ids,
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


async def seed_initial_user_data(user_id: str) -> None:
    """Seed the onboarding todo. The welcome conversation is seeded by the
    intelligence pipeline, not here."""
    try:
        log.info(f"{LogTag.ONBOARDING} Starting data seeding for user", user_id=user_id)
        await seed_onboarding_todo(user_id)
        log.info(f"{LogTag.ONBOARDING} Completed data seeding for user", user_id=user_id)

    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error in seed_initial_user_data for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
