"""Daily sweep pausing the workflows of users who have gone dormant."""

from typing import Any

from app.services.workflow.dormancy import sweep_dormant_workflows
from shared.py.wide_events import log


async def sweep_dormant_user_workflows(_ctx: dict[str, Any]) -> str:
    """Pause every activated workflow owned by a dormant user.

    Idempotent: a workflow already paused is no longer activated, so the next
    run does not see it. A user who returns has their pauses undone by the
    reactivate_user task their first activity queues, not by this sweep.
    """
    result = await sweep_dormant_workflows()
    log.set(
        dormant_users=result.dormant_users,
        workflows_paused=result.workflows_paused,
        pause_failures=result.failures,
    )
    return (
        f"sweep_dormant_user_workflows paused {result.workflows_paused} workflow(s) "
        f"across {result.dormant_users} dormant user(s), {result.failures} failure(s)"
    )
