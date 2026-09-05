"""Existing-user rollout — no cold starts.

For each existing user: provision the briefing workflows. Users we can derive a
goal for get a real first briefing next morning; sparse users with no derivable
goal have their briefings held (``briefing_bootstrap`` marker) until a goal
memory arrives or the grace window elapses. The user-facing announcement is a
manual email, not an in-app notification, so this only provisions and gates.
"""

from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.services.briefing import context
from app.services.system_workflows.provisioner import provision_briefing_workflows
from app.services.user_service import get_user_by_id
from app.utils.analytics import track
from shared.py.wide_events import log

# When we can't derive a goal AND the account is this sparse, hold for bootstrap
# instead of guessing a goal.
_SPARSE_INTEGRATION_MAX = 1


async def _is_sparse_account(user_id: str) -> bool:
    integrations = await user_integration_repository.count_for_user(user_id)
    if integrations > _SPARSE_INTEGRATION_MAX:
        return False
    gaia_todos = await todo_repository.count_gaia_assigned(user_id)
    return gaia_todos == 0


async def provision_existing_user(user_id: str) -> str:
    """Roll out briefings to one existing user. Returns the path taken.

    ``"normal"`` — goal derivable, briefings begin next day.
    ``"bootstrap"`` — sparse + no goal, briefings held until a goal arrives or the
    grace window elapses.
    """
    log.set(component="briefing_rollout", operation="provision_existing_user", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        log.warning("briefing_rollout.unknown_user", user_id=user_id)
        return "skipped"
    user["user_id"] = user_id

    await provision_briefing_workflows(user_id)

    _, has_goal = await context.format_goal_block(user_id, user)
    if not has_goal and await _is_sparse_account(user_id):
        await user_repository.set_briefing_bootstrap_pending(user_id)
        track(user_id, "briefing_provisioned", {"path": "bootstrap"})
        return "bootstrap"

    track(user_id, "briefing_provisioned", {"path": "normal"})
    return "normal"
