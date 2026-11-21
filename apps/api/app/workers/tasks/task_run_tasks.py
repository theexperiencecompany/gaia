"""The task engine's jobs: run_task brings one task round, recover_tasks re-arms lost ones.

run_task(task_id, stamp) is the one job every task time is armed with. A stamp that no
longer names one of the task's stored times is a job a reschedule left behind, and is
dropped. To-dos come round here (a repeat reopens, a nudge goes out); they never run.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import random

from app.constants.tasks import RECOVER_TASKS_BATCH, RECOVER_TASKS_JITTER_SECONDS, Assignee
from app.db.repositories.tasks import task_repository
from app.services.tasks.arming import arm_at, armed_for_current_time, come_round_times
from app.services.tasks.todo_rounds import bring_todo_round
from app.utils.occurrence import parse_occurrence_stamp
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log


async def run_task(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    task_id: str,
    stamp: int,
) -> str:
    """Bring the task round for the occurrence stamp names; a stale stamp is dropped."""
    log.set(task={"id": task_id, "stamp": stamp})
    armed_for = parse_occurrence_stamp(stamp, task_id)
    task = await task_repository.get_any(task_id)
    if task is None:
        return f"not_found:{task_id}"
    if armed_for is None or not armed_for_current_time(task, armed_for):
        log.set_ns("task", outcome="stale_occurrence")
        return f"stale_occurrence:{task_id}"
    if task.assignee is not Assignee.USER:
        raise NotImplementedError(f"GAIA task {task_id} cannot run on the task engine yet")
    with analytics_context(worker_context(Trigger.SCHEDULE)):
        outcome = await bring_todo_round(task, armed_for)
    log.set_ns("task", outcome=outcome.split(":", 1)[0])
    return outcome


async def recover_tasks(_ctx: Mapping[str, object]) -> str:
    """Re-arm every task whose time came while no job was queued for it, spread over a minute."""
    now = datetime.now(UTC)
    due = await task_repository.find_due_todos_all_users(now=now, limit=RECOVER_TASKS_BATCH)
    armed = 0
    for task in due:
        for moment in come_round_times(task):
            if moment > now:
                continue
            jitter = timedelta(seconds=random.randint(0, RECOVER_TASKS_JITTER_SECONDS))  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
            armed += await arm_at(task.id, moment, defer_until=now + jitter)
    log.set_ns("task_recovery", due=len(due), armed=armed)
    return f"armed:{armed} due:{len(due)}"
