"""Resume the workflows paused while their owner was dormant, once the owner comes back.

A workflow pauses for dormancy when it would next fire (execute_workflow_by_id), the same
rule a tracked todo follows. Resume only ever touches workflows carrying
DeactivationReason.USER_DORMANT, so one the user switched off themselves stays off.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


async def resume_dormancy_paused_workflows(user_id: str) -> int:
    """Re-activate the workflows paused for user_id's dormancy; return the count resumed.

    A workflow whose integrations are no longer connected cannot be
    re-activated — it is left paused and logged rather than failing the others.
    """
    resumed = 0

    for workflow in await workflow_repository.find_paused_for_reason(
        user_id, DeactivationReason.USER_DORMANT
    ):
        try:
            await WorkflowService.activate_workflow(workflow.id, user_id)
            resumed += 1
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Dormancy resume skipped workflow",
                workflow_id=workflow.id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if resumed:
        log.info(
            f"{LogTag.WORKFLOW} Resumed workflows paused for dormancy",
            user_id=user_id,
            resumed=resumed,
        )
    return resumed
