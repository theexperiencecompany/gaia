"""Arming: the one way a task's next time becomes a queued run_task job.

Every task comes round through run_task(task_id, stamp). The stamp names the
occurrence the job was armed for; ARQ cannot cancel a deferred job, so a job whose
task has moved off that time is rejected as stale when it fires. The job id is the
task and the stamp, so arming one occurrence twice queues it once.
"""

from datetime import UTC, datetime

from app.constants.tasks import RUN_TASK_JOB, Assignee, WhenKind
from app.models.task_models import TaskDocument
from app.utils.occurrence import occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job


def come_round_times(task: TaskDocument) -> list[datetime]:
    """Every stored time at which the task is owed a run_task job."""
    repeat_next = task.when.next_run if task.when.kind is WhenKind.REPEAT else None
    owed = task.nudge_at if task.assignee is Assignee.USER else task.next_check_at
    return [moment for moment in (repeat_next, owed) if moment is not None]


def armed_for_current_time(task: TaskDocument, armed_for: datetime) -> bool:
    """Whether a job armed for armed_for is for a time the task still names, to the second."""
    stamp = occurrence_stamp(armed_for)
    return any(occurrence_stamp(moment) == stamp for moment in come_round_times(task))


async def arm_at(task_id: str, moment: datetime, *, defer_until: datetime | None = None) -> bool:
    """Queue the run_task job for moment; False when that occurrence is already queued."""
    armed_for = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    stamp = occurrence_stamp(armed_for)
    job = await enqueue_worker_job(
        await RedisPoolManager.get_pool(),
        RUN_TASK_JOB,
        task_id,
        stamp,
        _job_id=f"{RUN_TASK_JOB}:{task_id}:{stamp}",
        _defer_until=defer_until or armed_for,
    )
    return job is not None


async def arm_task(task: TaskDocument) -> int:
    """Queue a job for every time the task is owed one; returns how many were newly queued."""
    if task.completed and task.when.kind is not WhenKind.REPEAT:
        return 0
    return sum([await arm_at(task.id, moment) for moment in come_round_times(task)])
