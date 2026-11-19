"""Resume everything GAIA paused while a user was dormant, once they come back.

Only work paused with DeactivationReason.USER_DORMANT is touched, so anything
the user switched off themselves stays off.
"""

from app.models.scheduler_models import DeactivationReason
from app.services.tracked_todo_service import tracked_todo_service
from app.services.workflow.dormancy import resume_dormancy_paused_workflows
from shared.py.wide_events import log


async def reactivate_user(user_id: str) -> int:
    """Resume user_id's dormancy-paused workflows and tracked todos; return the count resumed.

    A tracked todo that fails to resume raises, after the rest have resumed.
    """
    workflows = await resume_dormancy_paused_workflows(user_id)
    todos = await tracked_todo_service.resume_paused_for(user_id, DeactivationReason.USER_DORMANT)
    log.set_ns("reactivation", workflows_resumed=workflows, todos_resumed=todos)
    return workflows + todos
