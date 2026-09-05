"""Deactivate a user's workflows once their Dodo subscription lapses (paid-only gate),
and resume them once it's restored.

Mirrors ``integration_pause.py``/``dormancy.py``: both halves go through
``WorkflowService`` rather than a bulk repository write, because that is the path
that also unregisters/re-registers the workflow's Composio triggers — a workflow
left `activated=False` locally but still registered upstream keeps firing
regardless of billing state, and the same is true in reverse for a resume.

Resume only ever touches workflows carrying ``DeactivationReason.SUBSCRIPTION_LAPSED``,
so a workflow the user switched off themselves is never silently re-enabled.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


async def deactivate_workflows_for_lapsed_subscription(user_id: str) -> int:
    """Deactivate every activated workflow ``user_id`` owns. Returns the count
    deactivated. Idempotent — a user with no activated workflows is a no-op, and
    re-running against an already-deactivated workflow finds nothing to do. One
    workflow that fails to deactivate is logged and skipped rather than aborting
    the rest.
    """
    deactivated = 0

    for workflow in await workflow_repository.find_activated_for_user(user_id):
        try:
            await WorkflowService.deactivate_workflow(
                workflow.id, user_id, reason=DeactivationReason.SUBSCRIPTION_LAPSED
            )
            deactivated += 1
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Could not deactivate workflow for lapsed subscription",
                workflow_id=workflow.id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if deactivated:
        log.info(
            f"{LogTag.WORKFLOW} Deactivated workflows for lapsed subscription",
            user_id=user_id,
            deactivated=deactivated,
        )
    return deactivated


async def reactivate_workflows_for_restored_subscription(user_id: str) -> int:
    """Re-activate the workflows paused for ``user_id`` when their subscription lapsed.
    Returns the count resumed. Idempotent — a user with none paused for that reason is
    a no-op. Only touches workflows carrying ``DeactivationReason.SUBSCRIPTION_LAPSED``,
    so a workflow the user switched off themselves is never silently re-enabled. One
    workflow that fails to reactivate (e.g. a since-expired integration) is logged and
    skipped rather than aborting the rest.
    """
    reactivated = 0

    for workflow in await workflow_repository.find_paused_for_reason(
        user_id, DeactivationReason.SUBSCRIPTION_LAPSED
    ):
        try:
            await WorkflowService.activate_workflow(workflow.id, user_id)
            reactivated += 1
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Could not reactivate workflow for restored subscription",
                workflow_id=workflow.id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if reactivated:
        log.info(
            f"{LogTag.WORKFLOW} Reactivated workflows for restored subscription",
            user_id=user_id,
            reactivated=reactivated,
        )
    return reactivated
