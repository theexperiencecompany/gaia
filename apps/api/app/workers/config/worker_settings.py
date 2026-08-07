"""
ARQ worker settings configuration.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from arq.connections import RedisSettings

from app.config.settings import settings


class WorkerSettings:
    """
    ARQ worker settings configuration.
    This class defines the settings for the ARQ worker, including Redis connection,
    task functions, scheduled jobs, and performance settings.
    """

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # Task functions will be populated from the main worker file
    functions: list[Callable[..., Coroutine[Any, Any, str]]] = []

    # Cron jobs will be populated from the main worker file
    cron_jobs: list[Any] = []

    # Lifecycle functions will be set from the main worker file
    on_startup: Callable[[dict], Coroutine[Any, Any, None]] | None = None
    on_shutdown: Callable[[dict], Coroutine[Any, Any, None]] | None = None

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
    health_check_key = "arq:health"
    allow_abort_jobs = True
