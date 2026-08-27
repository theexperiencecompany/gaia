"""
ARQ worker settings configuration.
"""

from collections.abc import Callable, Coroutine
from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.typing import StartupShutdown

from app.config.settings import settings

#: The cap on one job. A workflow fire that reaches it is recorded as timed out
#: (workflow_tasks) rather than left "running" forever.
WORKER_JOB_TIMEOUT_SECONDS = 1800  # 30 minutes


class WorkerSettings:
    """
    ARQ worker settings configuration.
    This class defines the settings for the ARQ worker, including Redis connection,
    task functions, scheduled jobs, and performance settings.
    """

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # Task functions will be populated from the main worker file. ``...`` because
    # the registry is heterogeneous by design — each task takes the ARQ context
    # plus its own enqueue arguments. Not ARQ's ``WorkerCoroutine`` protocol: these
    # arrive already wrapped by ``instrument_task``, and a ``Callable`` value never
    # structurally matches that protocol's ``(ctx, *args, **kwargs)``. The return
    # type is the real contract every task shares and stays checked.
    functions: ClassVar[list[Callable[..., Coroutine[Any, Any, str]]]] = []

    # Cron jobs will be populated from the main worker file
    cron_jobs: ClassVar[list[CronJob]] = []

    # Lifecycle functions will be set from the main worker file
    on_startup: StartupShutdown | None = None
    on_shutdown: StartupShutdown | None = None

    # Performance settings
    # Sized from measured load, not guessed: mean task duration 10.9s at
    # 0.72 tasks/s needs ~8 concurrent (Little's Law), peaking near 16. Below
    # ~8 the queue grows without bound. Bursts above 10 are meant to queue.
    # Concurrency here is bounded by worker memory — each job holds agent
    # graphs and LLM contexts — so raise the container limit before raising it.
    max_jobs = 10
    job_timeout = WORKER_JOB_TIMEOUT_SECONDS
    keep_result = 0  # Don't keep results in Redis
    log_results = True
    health_check_interval = 30  # seconds
    health_check_key = "arq:health"
    allow_abort_jobs = True
