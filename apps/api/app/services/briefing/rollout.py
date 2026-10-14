"""Existing-user rollout: provision the briefing workflows, no cold starts.

Users with a derivable goal get a real first briefing next morning; sparse users
have briefings held (briefing_bootstrap marker) until a goal memory arrives or the
grace window elapses.
"""

from app.db.repositories.briefings import briefing_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.services.analytics_service import capture
from app.services.briefing import context
from app.services.system_workflows.provisioner import provision_briefing_workflows
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingProvisioned
from shared.py.wide_events import log

# When we can't derive a goal AND the account has at most this many integrations,
# hold for bootstrap instead of guessing a goal.
_SPARSE_INTEGRATION_MAX = 1


async def provision_existing_user(user_id: str) -> str:
    """Roll out briefings to one existing user and return the path taken.

    "normal": goal derivable, briefings begin next day. "bootstrap": sparse with no
    goal, briefings held until a goal arrives or the grace window elapses.
    "already_rolled_out": held or briefed before, state left as it is.
    """
    log.set(component="briefing_rollout", operation="provision_existing_user", user_id=user_id)
    user = await user_repository.get(user_id)
    if user is None:
        log.warning("briefing_rollout.unknown_user", user_id=user_id)
        return "skipped"

    await provision_briefing_workflows(user_id)

    # A user already held, or already briefed, keeps their state: a re-run of the
    # rollout must neither restart a grace window nor hold a user who is being briefed.
    if user.briefing_bootstrap is not None or await briefing_repository.has_daily_briefing(user_id):
        return "already_rolled_out"

    _, has_goal = await context.format_goal_block(user_id, user)
    integrations = await user_integration_repository.count_for_user(user_id)
    if not has_goal and integrations <= _SPARSE_INTEGRATION_MAX:
        await user_repository.set_briefing_bootstrap_pending(user_id)
        capture(UserId(user_id), BriefingProvisioned(held_for_goal=True))
        return "bootstrap"

    capture(UserId(user_id), BriefingProvisioned(held_for_goal=False))
    return "normal"
