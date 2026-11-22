"""The task engine's jobs: run_task brings one task round, recover_tasks re-arms lost ones.

resume_task continues a run parked on an approval once the user approved it; while
another run holds the task it waits on the lock backoff, then gives up loudly.

run_task(task_id, stamp) is the one job every task time is armed with. A stamp that no
longer names one of the task's stored times is a job a reschedule left behind, and is
dropped. To-dos come round here (a repeat reopens, a nudge goes out); they never run.
The same job runs a GAIA task on the app events its subscriptions took, with no stamp.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import random

from arq import Retry

from app.agents.core.background.task_run_delivery import (
    FinishedTaskRun,
    deliver_task_run,
    hand_unfinished_run_to_job,
    report_unfinished_run,
)
from app.constants.tasks import (
    RECOVER_TASKS_BATCH,
    RECOVER_TASKS_JITTER_SECONDS,
    RESUME_TASK_JOB,
    STALE_RUN_AFTER,
    Assignee,
    TaskLogEvent,
)
from app.constants.todos import (
    LOCK_DEFER_BACKOFF,
    MAX_RETRY_ATTEMPTS,
    TODO_RUN_FINISH_MAX_TRIES,
    TODO_RUN_FINISH_RETRY_DELAY,
)
from app.db.repositories.tasks import task_repository
from app.models.trigger_subscription_models import TriggerOrigin
from app.services.tasks.arming import arm_at, armed_for_current_time, come_round_times
from app.services.tasks.event_run import run_gaia_task_on_events
from app.services.tasks.gaia_run import resume_gaia_task, run_gaia_task
from app.services.tasks.run_records import record_event
from app.services.tasks.todo_rounds import bring_todo_round
from app.utils.occurrence import parse_occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from app.workers.task_envelope import ArqJobContext
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log


async def run_task(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    task_id: str,
    stamp: int | None,
    events: list[TriggerOrigin] | None = None,
    trigger_window: int | None = None,
) -> str:
    """Bring the task round for the occurrence stamp names, or run it on app events; a stale stamp is dropped.

    stamp is None for a run its subscriptions started: events are the ones it carries,
    trigger_window the window a drain of its buffered events was scheduled for.
    """
    log.set(task={"id": task_id, "stamp": stamp, "trigger_window": trigger_window})
    task = await task_repository.get_any(task_id)
    if task is None:
        return f"not_found:{task_id}"
    if stamp is None:
        if task.assignee is Assignee.USER:
            raise ValueError(f"task {task_id} is a to-do; app events never run it")
        with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
            outcome = await run_gaia_task_on_events(task, events or [], trigger_window)
        log.set_ns("task", outcome=outcome.split(":", 1)[0])
        return outcome
    armed_for = parse_occurrence_stamp(stamp, task_id)
    if armed_for is None or not armed_for_current_time(task, armed_for):
        log.set_ns("task", outcome="stale_occurrence")
        return f"stale_occurrence:{task_id}"
    with analytics_context(worker_context(Trigger.SCHEDULE)):
        if task.assignee is Assignee.USER:
            outcome = await bring_todo_round(task, armed_for)
        else:
            outcome = await run_gaia_task(task, armed_for)
    log.set_ns("task", outcome=outcome.split(":", 1)[0])
    return outcome


async def resume_task(
    _ctx: Mapping[str, object],
    task_id: str,
    conversation_id: str,
    approval_id: str,
    receipt: str,
    attempt: int = 0,
) -> str:
    """Continue the task's run parked on approval_id, waiting its turn while another run holds it."""
    log.set(task={"id": task_id, "approval_id": approval_id, "resume_attempt": attempt})
    outcome = await resume_gaia_task(task_id, conversation_id, approval_id, receipt)
    if outcome is not None:
        return outcome
    if attempt >= len(LOCK_DEFER_BACKOFF):
        log.warning("task.resume_dropped", task_id=task_id, approval_id=approval_id)
        # The grant entry said the run continues; the task's log must say it did not.
        if task := await task_repository.get_any(task_id):
            await record_event(
                task,
                TaskLogEvent.RESUME_DROPPED,
                f"{approval_id}: the run was not continued after the approval (the task stayed busy)",
            )
        return f"resume_dropped:{task_id}"
    await enqueue_worker_job(
        await RedisPoolManager.get_pool(),
        RESUME_TASK_JOB,
        task_id,
        conversation_id,
        approval_id,
        receipt,
        attempt + 1,
        _defer_until=datetime.now(UTC) + LOCK_DEFER_BACKOFF[attempt],
    )
    return f"resume_deferred:{task_id}"


async def recover_tasks(_ctx: Mapping[str, object]) -> str:
    """Re-arm every task whose time came while no job was queued for it, and free dead runs.

    A run still marked running long after its last write belongs to a worker that died:
    it goes back to idle, so its due time is re-armed like any other.
    """
    now = datetime.now(UTC)
    stale = await task_repository.find_stale_running_all_users(
        cutoff=now - STALE_RUN_AFTER, limit=RECOVER_TASKS_BATCH
    )
    for task in stale:
        log.warning("task.stale_run_reaped", task_id=task.id)
        await task_repository.finish_run(task.id, user_id=task.user_id, ran=None)
    due = [
        *await task_repository.find_due_todos_all_users(now=now, limit=RECOVER_TASKS_BATCH),
        *await task_repository.find_due_all_users(
            now=now, max_retries=MAX_RETRY_ATTEMPTS, limit=RECOVER_TASKS_BATCH
        ),
    ]
    armed = 0
    for task in due:
        for moment in come_round_times(task):
            if moment > now:
                continue
            jitter = timedelta(seconds=random.randint(0, RECOVER_TASKS_JITTER_SECONDS))  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
            armed += await arm_at(task.id, moment, defer_until=now + jitter)
    log.set_ns("task_recovery", due=len(due), armed=armed, reaped=len(stale))
    return f"armed:{armed} due:{len(due)} reaped:{len(stale)}"


async def finish_task_run(ctx: ArqJobContext, undone: FinishedTaskRun) -> str:
    """Finish the delivery a GAIA task run's own attempt could not: send, then record.

    The task is never run again for it. Each try picks up only what is still undone,
    so a message already sent is not sent twice.
    """
    log.set(task={"id": undone.task_id, "run_id": undone.run_id})
    left = await deliver_task_run(undone)
    if left is None:
        return f"finished:{undone.task_id}"
    if left.delivery != undone.delivery:
        # Sent on this try, record not closed: a replay of this job would send again.
        await hand_unfinished_run_to_job(left)
        return f"sent:{undone.task_id} (record handed on)"
    job_try = ctx["job_try"]
    if job_try < TODO_RUN_FINISH_MAX_TRIES:
        raise Retry(defer=TODO_RUN_FINISH_RETRY_DELAY * 2 ** (job_try - 1))
    report_unfinished_run(left, f"still failing after {job_try} tries")
    return f"failed:{undone.task_id} (gave up)"
