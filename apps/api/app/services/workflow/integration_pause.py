"""Pause a user's workflows when an integration they need dies, and resume on reconnect.

An activated workflow whose integration is dead is worse than a paused one: it
keeps firing on schedule, burns LLM spend, and delivers a failed or empty run
that reads to the user as "GAIA is broken" rather than "Gmail needs
reconnecting". Pausing turns an invisible failure into a visible, fixable state.

Both halves go through ``WorkflowService`` rather than the repository, so the
workflow's Composio trigger is unregistered upstream on pause and re-registered
on resume — a trigger left enabled on a dead account is upstream state GAIA no
longer tracks.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason
from app.services.workflow.integration_requirements import compute_required_integrations
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


async def pause_workflows_for_expired_integration(user_id: str, integration_id: str) -> list[str]:
    """Pause every activated workflow of ``user_id`` that needs ``integration_id``.

    Returns the titles of the workflows paused, for the user-facing notification.
    One workflow that fails to pause is logged and skipped rather than aborting
    the rest — a half-applied expiry is better than none.
    """
    paused: list[str] = []

    for workflow in await workflow_repository.find_activated_for_user(user_id):
        required = compute_required_integrations(workflow.steps, workflow.trigger_config)
        if integration_id not in required:
            continue
        try:
            await WorkflowService.deactivate_workflow(
                workflow.id, user_id, reason=DeactivationReason.INTEGRATION_EXPIRED
            )
            paused.append(workflow.title)
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Could not pause workflow for expired integration",
                workflow_id=workflow.id,
                user_id=user_id,
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if paused:
        log.info(
            f"{LogTag.WORKFLOW} Paused workflows for expired integration",
            user_id=user_id,
            integration_id=integration_id,
            paused=len(paused),
        )
    return paused


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
