"""Existing-user rollout: provision the briefing workflows, no cold starts.

Every user gets a first briefing next morning, goal or not. A user still in the
onboarding wizard is left to it: completing onboarding provisions their briefs on the
timezone it stores.
"""

from enum import StrEnum

from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.services.analytics_service import capture
from app.services.system_workflows.provisioner import provision_briefing_workflows
from app.utils.auth_utils import with_local_onboarding_completed
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingProvisioned
from shared.py.wide_events import log


class RolloutPath(StrEnum):
    """What the rollout did for one user."""

    NORMAL = "normal"
    ALREADY_ROLLED_OUT = "already_rolled_out"
    MID_ONBOARDING = "mid_onboarding"
    SKIPPED = "skipped"


async def provision_existing_user(user_id: str) -> RolloutPath:
    """Roll out briefings to one existing user and return the path taken.

    NORMAL: briefings begin next day. ALREADY_ROLLED_OUT: briefed before, left as it is.
    MID_ONBOARDING: the wizard provisions them.
    """
    log.set(component="briefing_rollout", operation="provision_existing_user", user_id=user_id)
    user = await user_repository.get(user_id)
    if user is None:
        log.warning("briefing_rollout.unknown_user", user_id=user_id)
        return RolloutPath.SKIPPED
    onboarding = with_local_onboarding_completed(user.onboarding)
    if onboarding is None or not onboarding.completed:
        return RolloutPath.MID_ONBOARDING

    await provision_briefing_workflows(user_id)

    if await briefing_repository.has_daily_briefing(user_id):
        return RolloutPath.ALREADY_ROLLED_OUT

    capture(UserId(user_id), BriefingProvisioned())
    return RolloutPath.NORMAL
