"""Pause a user's workflows when an integration they need dies, and resume on reconnect.

An activated workflow whose integration is dead is worse than a paused one: it
keeps firing on schedule, burns LLM spend, and delivers a failed or empty run
that reads to the user as "GAIA is broken" rather than "Gmail needs
reconnecting". Pausing turns an invisible failure into a visible, fixable state.

Both halves go through WorkflowService rather than the repository, so the
workflow's Composio trigger is unregistered upstream on pause and re-registered
on resume — a trigger left enabled on a dead account is upstream state GAIA no
longer tracks.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import (
    DeactivationReason,
    IntegrationRef,
    Workflow,
    WorkflowDocument,
    WorkflowUpdate,
)
from app.services.triggers.subscription_service import (
    pause_subscriptions_for_trigger_names,
    resync_subscriptions_for_trigger_names,
)
from app.services.workflow.integration_requirements import (
    compute_missing_integrations,
    compute_required_integrations,
    confirm_disconnected,
)
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


async def pause_workflows_for_expired_integration(user_id: str, integration_id: str) -> list[str]:
    """Pause every activated workflow of user_id that needs integration_id.

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


@dataclass(frozen=True, slots=True)
class PauseOutcome:
    """What a blocked-run claim came to: the blockers paused on, and the integrations the run had no business naming."""

    paused: list[str]
    unrelated: list[str]


async def pause_workflow_for_missing_integrations(
    workflow_id: str,
    user_id: str,
    integration_ids: Sequence[str],
    *,
    used_by_run: Sequence[str],
) -> PauseOutcome:
    """Pause one workflow whose run found integrations it needs unconnected.

    Only integrations the workflow's steps require or the run actually used
    count; anything else is reported as unrelated and nothing is paused. What
    passes is confirmed against real connection status, then stored on the
    workflow (blocked_on_integrations) since the resume side can't re-derive it.
    """
    workflow = await workflow_repository.get_for_user(workflow_id, user_id)
    if workflow is None:
        return PauseOutcome(paused=[], unrelated=list(dict.fromkeys(integration_ids)))
    required = compute_required_integrations(workflow.steps, workflow.trigger_config)
    claimed = list(dict.fromkeys(integration_ids))
    unrelated = [i for i in claimed if i not in required and i not in used_by_run]
    if unrelated:
        log.info(
            f"{LogTag.WORKFLOW} Blocked-run claim names integrations this run never needed",
            workflow_id=workflow_id,
            user_id=user_id,
            unrelated=unrelated,
            required=sorted(required),
            used_by_run=list(used_by_run),
        )
        return PauseOutcome(paused=[], unrelated=unrelated)

    confirmed = await confirm_disconnected(user_id, claimed)
    if not confirmed:
        log.info(
            f"{LogTag.WORKFLOW} Blocked-run claim did not check out — not pausing",
            workflow_id=workflow_id,
            user_id=user_id,
            claimed=claimed,
        )
        return PauseOutcome(paused=[], unrelated=[])

    # One write: a pause on record without its blockers could never be resumed,
    # since nothing but this list says what the run found missing.
    await WorkflowService.deactivate_workflow(
        workflow_id,
        user_id,
        reason=DeactivationReason.INTEGRATION_NEVER_CONNECTED,
        blocked_on_integrations=confirmed,
    )
    log.info(
        f"{LogTag.WORKFLOW} Paused workflow — a run found integrations never connected",
        workflow_id=workflow_id,
        user_id=user_id,
        integrations=confirmed,
    )
    return PauseOutcome(paused=confirmed, unrelated=[])


def _wants_integration(
    workflow: WorkflowDocument, integration_id: str, reason: DeactivationReason
) -> bool:
    """Whether reconnecting integration_id should un-pause this workflow.

    For an expiry, only the declared steps count. For a blocked run, the
    workflow's own found blockers take precedence, but declared steps are
    still checked — a false resume just re-pauses on the next run, while a
    missed one leaves the workflow dead until the user edits it.
    """
    required = compute_required_integrations(workflow.steps, workflow.trigger_config)
    if integration_id in required:
        return True
    return (
        reason is DeactivationReason.INTEGRATION_NEVER_CONNECTED
        and integration_id in workflow.blocked_on_integrations
    )


async def pause_workflow_before_fire(workflow: Workflow) -> list[IntegrationRef]:
    """Pause workflow before it fires when an integration it needs is not connected.

    Complements pause_workflows_for_expired_integration, which relies on a
    Composio webhook that a revoked/missing webhook or a never-connected
    integration never sends — without this a workflow fires forever (186 of
    649 bot messages in production were repeats, one thread had 22 identical).
    """
    required = compute_required_integrations(workflow.steps, workflow.trigger_config)
    missing = await compute_missing_integrations(required, workflow.user_id)
    if not missing or not workflow.id:
        return []

    await WorkflowService.deactivate_workflow(
        workflow.id,
        workflow.user_id,
        reason=DeactivationReason.INTEGRATION_NEVER_CONNECTED,
        blocked_on_integrations=[ref.id for ref in missing],
    )
    log.warning(
        f"{LogTag.WORKFLOW} Workflow paused at fire time — required integration not connected",
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        missing_integrations=[ref.id for ref in missing],
    )
    return missing


def _trigger_names_for_integration(integration_id: str) -> set[str]:
    """Return the GAIA-facing trigger names an integration publishes."""
    integration = get_integration_by_id(integration_id)
    if integration is None:
        return set()
    return {
        t.workflow_trigger_schema.slug
        for t in integration.associated_triggers
        if t.workflow_trigger_schema
    }


async def resume_workflows_for_reconnected_integration(user_id: str, integration_id: str) -> int:
    """Re-activate the workflows paused for integration_id, now that it is back.

    Only touches workflows the system paused (INTEGRATION_EXPIRED,
    INTEGRATION_NEVER_CONNECTED) — a workflow the user switched off stays off.
    One still missing another integration is left paused for a later reconnect.
    """
    resumed = 0

    for reason in (
        DeactivationReason.INTEGRATION_EXPIRED,
        DeactivationReason.INTEGRATION_NEVER_CONNECTED,
    ):
        for workflow in await workflow_repository.find_paused_for_reason(user_id, reason):
            if not _wants_integration(workflow, integration_id, reason):
                continue
            # The stored blockers are what the run found, beyond the declared
            # steps that activate_workflow checks: with one of several back, the
            # rest still block, and the list is trimmed to what is still missing.
            still_missing = await confirm_disconnected(user_id, workflow.blocked_on_integrations)
            if still_missing:
                await workflow_repository.update_for_user(
                    workflow.id, user_id, WorkflowUpdate(blocked_on_integrations=still_missing)
                )
                log.info(
                    f"{LogTag.WORKFLOW} Workflow left paused — still blocked on other integrations",
                    workflow_id=workflow.id,
                    user_id=user_id,
                    integration_id=integration_id,
                    still_missing=still_missing,
                )
                continue
            try:
                await WorkflowService.activate_workflow(workflow.id, user_id)
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
                continue
            # The block is over, so the record of it must not outlive it: a
            # stale list would resume this workflow on a later, unrelated
            # reconnect of the same integration.
            if workflow.blocked_on_integrations:
                await workflow_repository.update_for_user(
                    workflow.id, user_id, WorkflowUpdate(blocked_on_integrations=[])
                )
            resumed += 1

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
