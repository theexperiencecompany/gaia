"""The ARQ worker that runs browser jobs, on their own queue (a sidecar worker).

ARQ gives every job a worker starts an in-progress key that lives for the longest
function timeout on that worker, and a job whose worker died is not picked up
again until the key expires. A browser job's deadline is hours, so registered on
the main worker it would hold every crashed 30-minute job for hours. This second
arq Worker keeps that TTL to browser jobs, which cannot resume after a crash
anyway: their browser session died with the process.
"""

from collections.abc import MutableMapping
import socket
from typing import cast

from arq import cron
from arq.cron import CronJob
from arq.typing import WorkerCoroutine
from arq.worker import Worker

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_REAP_EVERY_SECONDS,
    BROWSER_JOB_TASK,
)
from app.services.browser.job_lifetime import browser_job_deadline_seconds
from app.workers.config.worker_settings import WorkerSettings
from app.workers.sidecar_worker import SIGNALS_STAY_WITH_MAIN_WORKER, start_sidecar_worker
from app.workers.task_envelope import arq_function, arq_task
from app.workers.tasks.browser_tasks import reap_browser_jobs, run_browser_job

#: The name its serving task is known by, in a stuck-task dump or an unobserved failure.
BROWSER_WORKER_NAME = "browser_worker"


def browser_reaper_cron() -> CronJob:
    """Return the sweep that makes good a browser worker that died, for the main worker to run.

    Not on the browser queue: a job slot there is held for hours by a run, so
    a reaper queued behind them would wait out the very runs it watches.
    """
    return cron(
        cast(WorkerCoroutine, arq_task(reap_browser_jobs)),
        second=set(range(0, 60, BROWSER_JOB_REAP_EVERY_SECONDS)),
    )


def browser_worker_health_key() -> str:
    """Return the key this host's browser worker refreshes while it polls its queue (ARQ's health check)."""
    return f"{BROWSER_JOB_QUEUE}:health:{socket.gethostname()}"


def build_browser_worker() -> Worker:
    """Build the arq Worker for the browser queue; signals stay with the main worker."""
    # One run per conversation is enforced by the browser slot lease, not by ARQ,
    # and a run is not idempotent (it may already have submitted a form): no retries.
    browser_job = arq_function(
        run_browser_job,
        name=BROWSER_JOB_TASK,
        timeout_seconds=browser_job_deadline_seconds(),
        max_tries=1,
        keep_result=0,
    )
    return Worker(
        functions=[browser_job],
        queue_name=BROWSER_JOB_QUEUE,
        redis_settings=WorkerSettings.redis_settings,
        **SIGNALS_STAY_WITH_MAIN_WORKER,
        max_jobs=settings.ARQ_BROWSER_MAX_JOBS,
        keep_result=0,
        health_check_interval=WorkerSettings.health_check_interval,
        health_check_key=browser_worker_health_key(),
        allow_abort_jobs=True,
    )


def start_browser_worker(ctx: MutableMapping[str, object]) -> None:
    """Start serving the browser queue beside the main worker."""
    start_sidecar_worker(ctx, BROWSER_WORKER_NAME, build_browser_worker())
