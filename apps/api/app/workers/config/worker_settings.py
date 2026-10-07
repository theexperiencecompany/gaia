"""ARQ worker settings configuration."""

from collections.abc import Callable, Coroutine
import socket
from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.typing import StartupShutdown
from arq.worker import Function

from app.config.settings import settings

#: The cap on one job, enforced by the task envelope (app.workers.task_envelope)
#: so a job that reaches it fails with reason task_timeout. A workflow fire that
#: reaches it is recorded as timed out (workflow_tasks) rather than left "running".
WORKER_JOB_TIMEOUT_SECONDS = 1800  # 30 minutes
#: How far past the envelope's deadline ARQ's own timeout sits. ARQ cancels at its
#: timeout, which reads as a clean cancel; the grace lets the envelope's deadline
#: fire first and the task's cancel cleanup finish, so ARQ's is only a backstop.
ARQ_BACKSTOP_GRACE_SECONDS = 60

#: What a worker registers: an arq Function, or a task wrapped by arq_task.
WorkerFunction = Function | Callable[..., Coroutine[Any, Any, str]]


class WorkerSettings:
    """ARQ worker settings: Redis connection, task functions, scheduled jobs, and performance settings."""

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # Populated from the main worker file. Not ARQ's WorkerCoroutine protocol:
    # tasks arrive wrapped by instrument_task, and a Callable never
    # structurally matches (ctx, *args, **kwargs) — only the return type stays checked.
    functions: ClassVar[list[WorkerFunction]] = []

    # Cron jobs will be populated from the main worker file
    cron_jobs: ClassVar[list[CronJob]] = []

    # Lifecycle functions will be set from the main worker file
    on_startup: StartupShutdown | None = None
    on_shutdown: StartupShutdown | None = None

    # Performance settings — sized from measured load: 10.9s mean duration at
    # 0.72 tasks/s needs ~8 concurrent (Little's Law, peaks ~16); below ~8 the
    # queue grows unbounded. PER PROCESS: scale via ARQ_MAX_JOBS, not more workers.
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = WORKER_JOB_TIMEOUT_SECONDS + ARQ_BACKSTOP_GRACE_SECONDS
    keep_result = 0  # Don't keep results in Redis
    log_results = True
    health_check_interval = 30  # seconds
    # Per-worker, not fleet-wide: a shared key would answer "is ANY worker
    # alive", letting a wedged worker hide behind a healthy sibling while its
    # queue backs up silently. Hostname gives each worker its own key.
    health_check_key = f"arq:health:{socket.gethostname()}"
    allow_abort_jobs = True
