"""Deactivate a user's workflows once their Dodo subscription lapses, and resume them once restored.

Mirrors integration_pause.py/dormancy.py: both halves go through
WorkflowService rather than a bulk repository write, because that is the path
that also unregisters/re-registers the workflow's Composio triggers — a workflow
left activated=False locally but still registered upstream keeps firing
regardless of billing state, and the same is true in reverse for a resume.

Resume only ever touches workflows carrying DeactivationReason.SUBSCRIPTION_LAPSED,
so a workflow the user switched off themselves is never silently re-enabled.

A workflow that fails is attempted alongside the rest and then reported: nothing
sweeps this on a schedule, and by the time the pause runs the billing row already
carries the reported status, so a webhook redelivery never reaches the workflows
again. The remainder leaves this call as SubscriptionWorkflowSyncIncomplete.
"""

from collections.abc import Awaitable, Callable

from app.constants.log_tags import LogTag
from app.constants.payments import SubscriptionWorkflowSync
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason, WorkflowDocument
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


class SubscriptionWorkflowSyncIncomplete(Exception):
    """Some of the user's workflows did not follow their billing state.

    Raised only after the whole batch has been attempted, so the workflows that
    did move stay moved; it marks the remainder as owed work, not the run as
    abandoned.
    """

    def __init__(self, user_id: str, failed_workflow_ids: list[str]) -> None:
        super().__init__(
            f"{len(failed_workflow_ids)} workflow(s) did not follow the subscription change"
        )
        self.user_id = user_id
        self.failed_workflow_ids = failed_workflow_ids


async def lapsable_workflows(user_id: str) -> list[WorkflowDocument]:
    """Return the workflows a lapsed subscription pauses.

    Every activated workflow the user owns except public templates, which
    stay live for everyone who copied them.
    """
    return [
        w for w in await workflow_repository.find_activated_for_user(user_id) if not w.is_public
    ]


async def deactivate_workflows_for_lapsed_subscription(user_id: str) -> int:
    """Deactivate every lapsable workflow user_id owns; return the count deactivated.

    Idempotent. One workflow that fails to deactivate does not abort the rest;
    the batch then raises SubscriptionWorkflowSyncIncomplete so the remainder
    is retried.
    """
    deactivated = 0
    failed: list[str] = []

    for workflow in await lapsable_workflows(user_id):
        try:
            await WorkflowService.deactivate_workflow(
                workflow.id, user_id, reason=DeactivationReason.SUBSCRIPTION_LAPSED
            )
            deactivated += 1
        except Exception as e:
            failed.append(workflow.id)
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
    if failed:
        raise SubscriptionWorkflowSyncIncomplete(user_id, failed)
    return deactivated


async def reactivate_workflows_for_restored_subscription(user_id: str) -> int:
    """Re-activate the workflows paused for user_id when their subscription lapsed.

    Returns the count resumed. Idempotent, and only touches workflows carrying
    DeactivationReason.SUBSCRIPTION_LAPSED, so one the user switched off themselves
    is never silently re-enabled. A workflow that fails does not abort the rest; the
    batch then raises SubscriptionWorkflowSyncIncomplete.
    """
    reactivated = 0
    failed: list[str] = []

    for workflow in await workflow_repository.find_paused_for_reason(
        user_id, DeactivationReason.SUBSCRIPTION_LAPSED
    ):
        try:
            await WorkflowService.activate_workflow(workflow.id, user_id)
            reactivated += 1
        except Exception as e:
            failed.append(workflow.id)
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
    if failed:
        raise SubscriptionWorkflowSyncIncomplete(user_id, failed)
    return reactivated


#: Both halves take a user id and answer how many workflows moved, so the retry
#: task dispatches straight through this rather than adapting either of them.
SYNC_ACTIONS: dict[SubscriptionWorkflowSync, Callable[[str], Awaitable[int]]] = {
    SubscriptionWorkflowSync.PAUSE: deactivate_workflows_for_lapsed_subscription,
    SubscriptionWorkflowSync.RESUME: reactivate_workflows_for_restored_subscription,
}
