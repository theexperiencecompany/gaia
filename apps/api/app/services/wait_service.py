"""Waits: remember who to pick back up when GAIA asks the user to do something, and queue them once done.

An ask site calls wait_for_user with the run that asked; the site where the thing gets done
calls report_wait_met. Each wait becomes one resume_waiter job (wait_tasks), which claims it and
picks the waiter back up however its kind resumes: a chat, a tracked todo or a workflow.
"""

from app.constants.log_tags import LogTag
from app.constants.waits import RESUME_WAITER_TASK, WaitCondition, WaiterKind
from app.db.repositories.waits import wait_repository
from app.models.agent_config import AgentConfigurableView
from app.models.wait_models import WaitKey, WaitUpdate
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


def _waiter(run: AgentConfigurableView) -> tuple[WaiterKind, str] | None:
    """Who the run speaks for: the user's chat, or the todo or workflow a background run executes."""
    if run.execution_mode == "background":
        if run.active_todo_id:
            return WaiterKind.TODO, run.active_todo_id
        if run.workflow_id:
            return WaiterKind.WORKFLOW, run.workflow_id
        return None
    if run.conversation_id:
        return WaiterKind.CHAT, run.conversation_id
    return None


async def wait_for_user(
    run: AgentConfigurableView,
    user_id: str,
    condition: WaitCondition,
    subject_id: str,
    subject_name: str,
) -> None:
    """Keep the run's waiter until the user meets condition on subject_id; a run speaking for nobody keeps nothing."""
    waiter = _waiter(run)
    if waiter is None:
        return
    kind, waiter_id = waiter
    await wait_repository.keep(
        WaitKey(
            user_id=user_id,
            condition=condition,
            subject_id=subject_id,
            waiter=kind,
            waiter_id=waiter_id,
        ),
        WaitUpdate(subject_name=subject_name, stream_id=run.stream_id),
    )


async def report_wait_met(user_id: str, condition: WaitCondition, subject_id: str) -> None:
    """Queue a resume for every waiter on the subject; never fails the caller, whose change already committed.

    The waits stay on file until their job claims them, so one that could not be queued is
    picked up by the next report instead of being lost.
    """
    try:
        waits = await wait_repository.find_met(user_id, condition, subject_id)
        if not waits:
            return
        pool = await RedisPoolManager.get_pool()
        for wait in waits:
            await enqueue_worker_job(pool, RESUME_WAITER_TASK, user_id, wait.id)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Failed to queue the waiters on a met condition",
            condition=condition.value,
            subject_id=subject_id,
            error=str(e),
            error_type=type(e).__name__,
        )
