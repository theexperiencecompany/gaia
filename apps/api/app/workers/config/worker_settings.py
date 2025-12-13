"""
ARQ worker settings configuration.
"""

from typing import Callable, Optional, Any, Coroutine
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
    on_startup: Optional[Callable[[dict], Coroutine[Any, Any, None]]] = None
    on_shutdown: Optional[Callable[[dict], Coroutine[Any, Any, None]]] = None

    # Performance settings
    max_jobs = 10
    job_timeout = 300  # 5 minutes
    keep_result = 0  # Don't keep results in Redis
    log_results = True
    health_check_interval = 30  # seconds
    health_check_key = "arq:health"
    allow_abort_jobs = True
