"""The workers for brief runs and their scout refreshes, each on its own queue with its own concurrency.

An hour's briefs land in the same half hour (workers.brief_slots), so on the shared queue they
held every other job behind them. A brief's fire takes the brief queue because its system
workflow declares it (system_workflows.definitions.briefing); its scouts are refreshed on
theirs ahead of its slot, so the brief rarely waits on an app.
"""

from arq.worker import Worker

from app.constants.brief_slots import (
    BRIEF_QUEUE,
    BRIEF_QUEUE_MAX_JOBS,
    SCOUT_QUEUE,
    SCOUT_QUEUE_MAX_JOBS,
)
from app.constants.scouts import REFRESH_SCOUTS_TASK
from app.constants.workflows import EXECUTE_WORKFLOW_TASK
from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS
from app.workers.queue_workers import queue_worker
from app.workers.task_envelope import arq_function
from app.workers.tasks.scout_tasks import refresh_scouts_task
from app.workers.tasks.workflow_tasks import execute_workflow_by_id


def build_brief_worker() -> Worker:
    """Build the arq Worker that runs brief fires, BRIEF_QUEUE_MAX_JOBS at a time."""
    # mutmut reads a keyword argument's pragma on its call's first line.
    fire = arq_function(  # pragma: no mutate — name=None registers the same name
        execute_workflow_by_id,
        name=EXECUTE_WORKFLOW_TASK,
        timeout_seconds=WORKER_JOB_TIMEOUT_SECONDS,
    )
    return queue_worker(BRIEF_QUEUE, [fire], max_jobs=BRIEF_QUEUE_MAX_JOBS)


def build_scout_worker() -> Worker:
    """Build the arq Worker that refreshes briefs' scouts, SCOUT_QUEUE_MAX_JOBS at a time."""
    refresh = arq_function(
        refresh_scouts_task,
        name=REFRESH_SCOUTS_TASK,
        timeout_seconds=WORKER_JOB_TIMEOUT_SECONDS,
    )
    return queue_worker(SCOUT_QUEUE, [refresh], max_jobs=SCOUT_QUEUE_MAX_JOBS)
