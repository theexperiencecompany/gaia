"""Post-onboarding data seeding."""

from app.constants.log_tags import LogTag
from app.services.system_workflows.provisioner import provision_universal_system_workflows
from app.utils.seeding_utils import seed_onboarding_todo
from shared.py.wide_events import log


async def seed_initial_user_data(user_id: str) -> None:
    """Seed the onboarding todo and the universal system workflows. The welcome
    conversation is seeded by the intelligence pipeline, not here.

    Runs after complete_onboarding() has written the profile timezone, which is
    what the provisioner stamps onto the briefing schedules. Silent, like the
    per-integration provisioning during onboarding: the onboarding UI surfaces
    the workflows itself.
    """
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

    await provision_universal_system_workflows(user_id, notify=False)
