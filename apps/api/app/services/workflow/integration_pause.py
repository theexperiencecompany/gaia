"""Pause a user's workflows when an integration they need dies.

An activated workflow whose integration is dead is worse than a paused one: it
keeps firing on schedule, burns LLM spend, and delivers a failed or empty run
that reads to the user as "GAIA is broken" rather than "Gmail needs
reconnecting". Pausing turns an invisible failure into a visible, fixable state.

Deactivation goes through the repository rather than
``WorkflowService.deactivate_workflow`` (the path ``dormancy`` uses), because
this module runs inside the Composio tool wrapper's reach: importing
``workflow.service`` from here closes an import cycle back through
``composio_service``. The difference is that the workflow's Composio trigger is
not unregistered upstream. That is safe *here specifically* — the trigger is
bound to the connected account that just died, so it cannot deliver, and the
repository write clears ``composio_trigger_ids`` so a stray delivery matches no
workflow. Reconnecting strands those upstream triggers exactly as any reconnect
already does (see ``handle_oauth_connection``), and re-registers fresh ones.

The resume half lives in ``integration_resume`` — it needs ``WorkflowService``
and is only reached from the OAuth reconnect path, which is outside that cycle.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason
from app.services.workflow.integration_requirements import compute_required_integrations
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
            await workflow_repository.deactivate(
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
