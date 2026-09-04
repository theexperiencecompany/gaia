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

from collections.abc import Sequence

from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason, WorkflowDocument, WorkflowUpdate
from app.services.triggers.subscription_service import (
    pause_subscriptions_for_trigger_names,
    resync_subscriptions_for_trigger_names,
)
from app.services.workflow.integration_requirements import (
    compute_required_integrations,
    confirm_disconnected,
)
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

    # Todo subscriptions on this integration's triggers die with the connection
    # too. They pause rather than deactivate (todos have no activated flag) and
    # their todos gain the blocking label, so a dead watch is visible.
    await pause_subscriptions_for_trigger_names(
        user_id, _trigger_names_for_integration(integration_id)
    )

    if paused:
        log.info(
            f"{LogTag.WORKFLOW} Paused workflows for expired integration",
            user_id=user_id,
            integration_id=integration_id,
            paused=len(paused),
        )
    return paused


async def pause_workflow_for_missing_integrations(
    workflow_id: str, user_id: str, integration_ids: Sequence[str]
) -> list[str]:
    """Pause one workflow whose run found integrations it needs unconnected.

    Returns the integrations that were confirmed missing — empty when the claim
    did not check out, in which case nothing is paused and the caller treats the
    run as an ordinary decline. The confirmed list is stored on the workflow
    because the resume side cannot re-derive it; see
    ``WorkflowDocument.blocked_on_integrations``.
    """
    confirmed = await confirm_disconnected(user_id, integration_ids)
    if not confirmed:
        log.info(
            f"{LogTag.WORKFLOW} Blocked-run claim did not check out — not pausing",
            workflow_id=workflow_id,
            user_id=user_id,
            claimed=list(integration_ids),
        )
        return []

    await WorkflowService.deactivate_workflow(
        workflow_id, user_id, reason=DeactivationReason.INTEGRATION_NEVER_CONNECTED
    )
    # After the deactivation, which owns `activated`/`deactivated_reason`.
    await workflow_repository.update_for_user(
        workflow_id, user_id, WorkflowUpdate(blocked_on_integrations=confirmed)
    )
    log.info(
        f"{LogTag.WORKFLOW} Paused workflow — a run found integrations never connected",
        workflow_id=workflow_id,
        user_id=user_id,
        integrations=confirmed,
    )
    return confirmed


def _wants_integration(
    workflow: WorkflowDocument, integration_id: str, reason: DeactivationReason
) -> bool:
    """Whether reconnecting ``integration_id`` should un-pause this workflow.

    For an expiry the declared steps are the only record of what it needs. For a
    blocked run the workflow carries what the run actually found, which is the
    better answer — but the declared steps are still consulted, because resuming
    a workflow that is still blocked costs one run that pauses it again, while
    failing to resume one leaves it dead until the user edits it.
    """
    required = compute_required_integrations(workflow.steps, workflow.trigger_config)
    if integration_id in required:
        return True
    return (
        reason is DeactivationReason.INTEGRATION_NEVER_CONNECTED
        and integration_id in workflow.blocked_on_integrations
    )


def _trigger_names_for_integration(integration_id: str) -> set[str]:
    """The GAIA-facing trigger names an integration publishes."""
    integration = get_integration_by_id(integration_id)
    if integration is None:
        return set()
    return {
        t.workflow_trigger_schema.slug
        for t in integration.associated_triggers
        if t.workflow_trigger_schema
    }


async def resume_workflows_for_reconnected_integration(user_id: str, integration_id: str) -> int:
    """Re-activate the workflows paused for ``integration_id``, now that it is back.

    Only touches workflows the system paused — ``INTEGRATION_EXPIRED`` (a live
    connection died) and ``INTEGRATION_NEVER_CONNECTED`` (a run found one that
    was never connected) — so a workflow the user switched off themselves is
    never silently re-enabled. One still missing another integration cannot be
    re-activated — ``activate_workflow`` raises and it is left paused for a
    later reconnect.
    """
    resumed = 0

    for reason in (
        DeactivationReason.INTEGRATION_EXPIRED,
        DeactivationReason.INTEGRATION_NEVER_CONNECTED,
    ):
        for workflow in await workflow_repository.find_paused_for_reason(user_id, reason):
            if not _wants_integration(workflow, integration_id, reason):
                continue
            try:
                await WorkflowService.activate_workflow(workflow.id, user_id)
                # The block is over, so the record of it must not outlive it:
                # a stale list would resume this workflow on a later, unrelated
                # reconnect of the same integration.
                if workflow.blocked_on_integrations:
                    await workflow_repository.update_for_user(
                        workflow.id, user_id, WorkflowUpdate(blocked_on_integrations=[])
                    )
                resumed += 1
            except Exception as e:
                log.info(
                    f"{LogTag.WORKFLOW} Workflow left paused — still missing an integration",
                    workflow_id=workflow.id,
                    user_id=user_id,
                    integration_id=integration_id,
                    reason=reason.value,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    # Mirror of the pause side: the reconnect gives the subscriptions a fresh
    # connected account, so they re-register and drop the blocking label.
    await resync_subscriptions_for_trigger_names(
        user_id, _trigger_names_for_integration(integration_id)
    )

    if resumed:
        log.info(
            f"{LogTag.WORKFLOW} Resumed workflows after integration reconnect",
            user_id=user_id,
            integration_id=integration_id,
            resumed=resumed,
        )
    return resumed
