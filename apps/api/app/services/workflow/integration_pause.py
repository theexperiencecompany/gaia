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

from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason, IntegrationRef, Workflow
from app.services.triggers.subscription_service import (
    pause_subscriptions_for_trigger_names,
    resync_subscriptions_for_trigger_names,
)
from app.services.workflow.integration_requirements import (
    compute_missing_integrations,
    compute_required_integrations,
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


async def pause_workflow_for_missing_integrations(workflow: Workflow) -> list[IntegrationRef]:
    """Pause ``workflow`` when an integration it needs is not connected; return what was missing.

    The fire-time counterpart of :func:`pause_workflows_for_expired_integration`,
    which only runs when Composio delivers a connection-lifecycle webhook. A grant
    revoked upstream, a webhook that never arrived, or an integration the user
    never connected produces no such event, so the workflow stays activated and
    every occurrence fires, spends a run and delivers another "X isn't connected"
    message — 186 of 649 bot messages in the production sample, one thread with 22
    identical ones. Pausing on the first such fire turns that into one notice;
    reconnecting resumes it through
    :func:`resume_workflows_for_reconnected_integration`, which only reactivates
    workflows carrying this same reason.

    Returns an empty list when nothing is missing (the fire may proceed).
    """
    required = compute_required_integrations(workflow.steps, workflow.trigger_config)
    missing = await compute_missing_integrations(required, workflow.user_id)
    if not missing or not workflow.id:
        return []

    await WorkflowService.deactivate_workflow(
        workflow.id, workflow.user_id, reason=DeactivationReason.INTEGRATION_EXPIRED
    )
    log.warning(
        f"{LogTag.WORKFLOW} Workflow paused at fire time — required integration not connected",
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        missing_integrations=[ref.id for ref in missing],
    )
    return missing


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
