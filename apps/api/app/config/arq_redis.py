"""The one connection every ARQ client and the ARQ worker make to Redis."""

from dataclasses import replace

from arq.connections import RedisSettings

from app.config.settings import settings
from app.constants.db import ARQ_REDIS_CONNECT_TIMEOUT_SECONDS


def arq_redis_settings() -> RedisSettings:
    """Return ARQ's settings for REDIS_URL, with a connect deadline a busy booting process meets."""
    return replace(
        RedisSettings.from_dsn(settings.REDIS_URL), conn_timeout=ARQ_REDIS_CONNECT_TIMEOUT_SECONDS
    )
