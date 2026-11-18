"""Existing-user rollout: provision the briefing workflows, no cold starts.

Users with a derivable goal get a real first briefing next morning; sparse users
have briefings held (the briefing state's bootstrap marker) until a goal memory arrives or the
grace window elapses. A user still in the onboarding wizard is left to it: completing
onboarding provisions their briefs on the timezone it stores.
"""

from enum import StrEnum

from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.services.analytics_service import capture
from app.services.briefing.goals import stated_goals
from app.services.system_workflows.provisioner import provision_briefing_workflows
from app.utils.auth_utils import with_local_onboarding_completed
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingProvisioned
from shared.py.wide_events import log


class RolloutPath(StrEnum):
    """What the rollout did for one user."""

    NORMAL = "normal"
    BOOTSTRAP = "bootstrap"
    ALREADY_ROLLED_OUT = "already_rolled_out"
    MID_ONBOARDING = "mid_onboarding"
    SKIPPED = "skipped"


# When we can't derive a goal AND the account has at most this many integrations,
# hold for bootstrap instead of guessing a goal.
_SPARSE_INTEGRATION_MAX = 1


async def provision_existing_user(user_id: str) -> RolloutPath:
    """Roll out briefings to one existing user and return the path taken.

    NORMAL: goal derivable, briefings begin next day. BOOTSTRAP: sparse with no goal,
    held until a goal arrives or the grace window elapses. ALREADY_ROLLED_OUT: held or
    briefed before, state left as it is. MID_ONBOARDING: the wizard provisions them.
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

    # A user already held, or already briefed, keeps their state: a re-run of the
    # rollout must neither restart a grace window nor hold a user who is being briefed.
    state = await briefing_state_repository.state_for(user_id)
    if state.bootstrap is not None or await briefing_repository.has_daily_briefing(user_id):
        return RolloutPath.ALREADY_ROLLED_OUT

    has_goal = bool(await stated_goals(user_id, user))
    integrations = await user_integration_repository.count_for_user(user_id)
    if not has_goal and integrations <= _SPARSE_INTEGRATION_MAX:
        await briefing_state_repository.hold_for_goal(user_id)
        capture(UserId(user_id), BriefingProvisioned(held_for_goal=True))
        return RolloutPath.BOOTSTRAP

    capture(UserId(user_id), BriefingProvisioned(held_for_goal=False))
    return RolloutPath.NORMAL
