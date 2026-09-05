"""Post-onboarding personalization service."""

from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.onboarding_models import PersonalizationBundle
from app.utils.seeding_utils import seed_onboarding_todo
from shared.py.wide_events import log


async def save_personalization_data(user_id: str, bundle: PersonalizationBundle) -> None:
    """Persist the generated personalization bundle for a user."""
    try:
        await user_repository.save_personalization(user_id, bundle)
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
