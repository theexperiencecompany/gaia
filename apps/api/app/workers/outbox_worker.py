"""The ARQ worker that runs outbox jobs on their own queue (a sidecar worker).

The main worker's slots fill with runs that take minutes; the outbox jobs (intake, flush
and the sweep that recovers a lost flush) are short, and a delay in them is a delayed
message or security alert. Their own Worker has its own slots, so they never wait behind a run.
"""

from collections.abc import MutableMapping
import socket

from arq import cron
from arq.worker import Worker, func

from app.config.settings import settings
from app.constants.outbox import OUTBOX_INTAKE_TASK, OUTBOX_JOB_QUEUE, OUTBOX_TASK_MAX_TRIES
from app.constants.outbox_attention import FLUSH_SWEEP_INTERVAL_MINUTES, OUTBOX_FLUSH_TASK
from app.workers.config.worker_settings import WorkerSettings
from app.workers.sidecar_worker import SIGNALS_STAY_WITH_MAIN_WORKER, start_sidecar_worker
from app.workers.task_envelope import arq_task
from app.workers.tasks.outbox_tasks import outbox_flush, outbox_flush_sweep, outbox_intake

#: The name its serving task is known by, in a stuck-task dump or an unobserved failure.
OUTBOX_WORKER_NAME = "outbox_worker"


def outbox_worker_health_key() -> str:
    """Return the key this host's outbox worker refreshes while it polls its queue (ARQ's health check)."""
    return f"{OUTBOX_JOB_QUEUE}:health:{socket.gethostname()}"


def build_outbox_worker() -> Worker:
    """Build the arq Worker for the outbox queue; signals stay with the main worker."""
    sweep = arq_task(outbox_flush_sweep)
    return Worker(
        functions=[
            func(arq_task(outbox_intake), name=OUTBOX_INTAKE_TASK, max_tries=OUTBOX_TASK_MAX_TRIES),
            func(arq_task(outbox_flush), name=OUTBOX_FLUSH_TASK, max_tries=OUTBOX_TASK_MAX_TRIES),
        ],
        # A held item whose flush job was lost is flushed within one interval.
        cron_jobs=[cron(sweep, minute=set(range(0, 60, FLUSH_SWEEP_INTERVAL_MINUTES)), second=0)],
        queue_name=OUTBOX_JOB_QUEUE,
        redis_settings=WorkerSettings.redis_settings,
        **SIGNALS_STAY_WITH_MAIN_WORKER,
        max_jobs=settings.ARQ_OUTBOX_MAX_JOBS,
        job_timeout=WorkerSettings.job_timeout,
        keep_result=0,
        health_check_interval=WorkerSettings.health_check_interval,
        health_check_key=outbox_worker_health_key(),
        allow_abort_jobs=True,
    )


def start_outbox_worker(ctx: MutableMapping[str, object]) -> None:
    """Start serving the outbox queue beside the main worker."""
    start_sidecar_worker(ctx, OUTBOX_WORKER_NAME, build_outbox_worker())
