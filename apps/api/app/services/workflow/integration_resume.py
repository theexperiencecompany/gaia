"""Re-activate the workflows paused when an integration expired.

Separate from ``integration_pause`` because re-activation needs
``WorkflowService`` (to re-register Composio triggers and re-check the
workflow's requirements), and importing that from the pause side would close an
import cycle: the pause runs inside the Composio tool wrapper's reach, and
``workflow.service`` imports ``generation_service`` -> the agent tool registry
-> ``composio_service``.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason
from app.services.workflow.integration_requirements import compute_required_integrations
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


async def resume_workflows_for_reconnected_integration(user_id: str, integration_id: str) -> int:
    """Re-activate the workflows paused for ``integration_id``, now that it is back.

    Only touches workflows carrying ``DeactivationReason.INTEGRATION_EXPIRED``, so
    a workflow the user switched off themselves is never silently re-enabled. One
    still missing another integration cannot be re-activated —
    ``activate_workflow`` raises and it is left paused for a later reconnect.
    """
    resumed = 0

    for workflow in await workflow_repository.find_paused_for_reason(
        user_id, DeactivationReason.INTEGRATION_EXPIRED
    ):
        required = compute_required_integrations(workflow.steps, workflow.trigger_config)
        if integration_id not in required:
            continue
        try:
            await WorkflowService.activate_workflow(workflow.id, user_id)
            resumed += 1
        except Exception as e:
            log.info(
                f"{LogTag.WORKFLOW} Workflow left paused — still missing an integration",
                workflow_id=workflow.id,
                user_id=user_id,
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if resumed:
        log.info(
            f"{LogTag.WORKFLOW} Resumed workflows after integration reconnect",
            user_id=user_id,
            integration_id=integration_id,
            resumed=resumed,
        )
    return resumed
