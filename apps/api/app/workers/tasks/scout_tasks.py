"""Scout work ahead of a brief: learn a newly connected integration, refresh a brief's scouts before its slot."""

from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.services.briefing.scouts.service import learn_connected_integration, refresh_scouts
from app.utils.occurrence import occurrence_stamp
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log


async def learn_scout_task(_ctx: ArqJobContext, user_id: str, integration_id: str) -> str:
    """Scout the new integration once; a failure raises so the job records it."""
    log.set(user_id=user_id, integration_id=integration_id)
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"no user {user_id} to scout {integration_id} for")
    result = await learn_connected_integration(user, integration_id)
    outcome = result.outcome.value if result is not None else "not_scouted"
    log.set_ns("scouts", learn_outcome=outcome)
    return f"learn_scout {integration_id}: {outcome}"


async def refresh_scouts_task(_ctx: ArqJobContext, workflow_id: str, scheduled_for: int) -> str:
    """Refresh the scouts of the brief armed for scheduled_for, unless that fire no longer stands.

    ARQ cannot cancel a deferred job, so a brief moved or switched off still sends this one;
    it runs only while the workflow is live and still armed for the same fire.
    """
    log.set(workflow_id=workflow_id)
    workflow = await workflow_repository.get(workflow_id)
    next_run = workflow.trigger_config.next_run if workflow is not None else None
    if workflow is None or not workflow.activated or next_run is None:
        log.set_ns("scouts", refresh="stale")
        return f"refresh_scouts {workflow_id}: no live brief"
    if occurrence_stamp(next_run) != scheduled_for:
        log.set_ns("scouts", refresh="stale")
        return f"refresh_scouts {workflow_id}: brief moved"
    user = await user_repository.get(workflow.user_id)
    if user is None:
        raise LookupError(f"no user {workflow.user_id} to refresh scouts for")
    log.set(user_id=user.id)
    await refresh_scouts(user)
    log.set_ns("scouts", refresh="kept")
    return f"refresh_scouts {workflow_id}: kept"
