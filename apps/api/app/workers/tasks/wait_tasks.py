"""Pick a waiter back up once the user did what GAIA asked, from the job report_wait_met queued.

Each WaiterKind resumes its own way: a chat's executor is handed the news, a tracked todo
gets a run, a workflow gets a run. Every one is told the same thing: what was done, how
long ago it was asked, and to stay read-only until the user confirms anything else.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import MappingProxyType

from app.agents.core.background.executor_runner import deliver_to_executor
from app.agents.prompts.wait_prompts import WAIT_MET_ENTRY, WAIT_MET_SENTENCES
from app.agents.tools.run_record import unblock_integration
from app.constants.agents import AgentTag
from app.constants.log_tags import LogTag
from app.constants.todos import EXECUTE_TRACKED_TODO_TASK
from app.constants.waits import (
    WAIT_MET_CONTEXT_KEY,
    WAIT_MET_TRIGGER,
    WaitCondition,
    WaiterKind,
)
from app.models.trigger_subscription_models import TriggerOrigin
from app.models.user_models import AuthenticatedUser
from app.models.wait_models import WaitDocument, WaitMetPayload
from app.services.analytics_service import capture
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.auth_utils import require_owner
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import age_since
from app.workers.queue import enqueue_worker_job
from app.workers.task_envelope import ArqJobContext
from shared.py.analytics import UserId
from shared.py.analytics.catalog.agents import WaitResumed
from shared.py.wide_events import log


class WorkflowNotQueuedError(RuntimeError):
    """A workflow waiter's run could not be queued; the job fails so the loss is seen."""


async def _resume_chat(wait: WaitDocument, user: AuthenticatedUser, entry: str) -> None:
    await deliver_to_executor(wait.waiter_id, user, entry, tag=AgentTag.WAIT_MET)


async def _resume_todo(wait: WaitDocument, _user: AuthenticatedUser, entry: str) -> None:
    # A trigger origin, not a plain run: a wake landing mid-run is held for the drain, not dropped.
    origin = TriggerOrigin(
        subscription_id=wait.id,
        trigger_name=WAIT_MET_TRIGGER,
        payload=WaitMetPayload(message=entry).model_dump(),
    )
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, EXECUTE_TRACKED_TODO_TASK, wait.waiter_id, origin)


async def _resume_workflow(wait: WaitDocument, user: AuthenticatedUser, entry: str) -> None:
    queued = await WorkflowQueueService.queue_workflow_execution(
        wait.waiter_id, user.user_id, context={WAIT_MET_CONTEXT_KEY: entry}
    )
    if not queued:
        raise WorkflowNotQueuedError(wait.waiter_id)


_RESUMERS: MappingProxyType[
    WaiterKind, Callable[[WaitDocument, AuthenticatedUser, str], Awaitable[None]]
] = MappingProxyType(
    {
        WaiterKind.CHAT: _resume_chat,
        WaiterKind.TODO: _resume_todo,
        WaiterKind.WORKFLOW: _resume_workflow,
    }
)


async def resume_waiter(_ctx: ArqJobContext, wait_json: str) -> str:
    """Tell the waiter what the user did and how long ago it was asked, then let it pick back up."""
    wait = WaitDocument.model_validate_json(wait_json)
    user = await require_owner(wait.user_id)
    # The asking run blocked the integration after its card; if it is still live it must be able to use it now.
    if wait.condition is WaitCondition.INTEGRATION_CONNECTED and wait.stream_id:
        await unblock_integration(wait.stream_id, wait.subject_id)
    entry = WAIT_MET_ENTRY.format(
        met=WAIT_MET_SENTENCES[wait.condition].format(name=wait.subject_name),
        age=age_since(wait.created_at),
    )
    await _RESUMERS[wait.waiter](wait, user, entry)
    waited_minutes = int((datetime.now(UTC) - wait.created_at).total_seconds()) // 60
    capture(
        UserId(wait.user_id),
        WaitResumed(
            condition=wait.condition.value,
            waiter=wait.waiter.value,
            waited_minutes=waited_minutes,
        ),
    )
    log.info(
        f"{LogTag.AGENT} Picked a waiter back up",
        condition=wait.condition.value,
        waiter=wait.waiter.value,
        waiter_id=wait.waiter_id,
        waited_minutes=waited_minutes,
    )
    return f"resume_waiter {wait.waiter.value}:{wait.waiter_id}"
