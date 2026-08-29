"""
ARQ worker settings configuration.
"""

from collections.abc import Callable, Coroutine
import socket
from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.typing import StartupShutdown

from app.config.settings import settings


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
    job_timeout = 1800  # 30 minutes
    keep_result = 0  # Don't keep results in Redis
    log_results = True
    health_check_interval = 30  # seconds
    # Per-worker, not fleet-wide. arq's ``record_health`` PSETEXes this key from
    # the poll loop, and ``scripts/arq_healthcheck.py`` — which runs inside each
    # worker container — is just EXISTS on it. A shared key therefore answers
    # "is ANY worker alive", so a wedged worker's own probe stays green as long
    # as a sibling is refreshing it: the container is never restarted, it holds a
    # replica slot doing nothing, and the queue backs up silently. The container
    # hostname is the natural per-worker identity because the probe runs in that
    # same container; arq's own default (queue name + suffix) is still shared
    # across workers on one queue, so it does not solve this either.
    health_check_key = f"arq:health:{socket.gethostname()}"
    allow_abort_jobs = True
