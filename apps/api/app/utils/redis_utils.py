"""Redis utilities for GAIA system."""

import asyncio
from typing import ClassVar

from arq.connections import ArqRedis

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


class RedisPoolManager:
    """Thread-safe singleton Redis pool manager."""

    _instance: ClassVar["RedisPoolManager | None"] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _pool: ClassVar[ArqRedis | None] = None

    def __new__(cls) -> "RedisPoolManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_pool(cls) -> ArqRedis:
        """Get or create Redis pool."""
        log.set(operation="redis_get_pool", component="RedisPoolManager")
        if cls._pool is not None:
            return cls._pool

        async with cls._lock:
            if cls._pool is None:
                # arq loads only when the lazy pool is first created.
                from arq import create_pool  # noqa: PLC0415 -- arq loads only when the
                from arq.connections import (  # noqa: PLC0415 -- arq loads only when the lazy pool is first created
                    RedisSettings,
                )

                # Settings load deferred until a pool is actually created.
                from app.config.settings import (  # noqa: PLC0415 -- settings on demand
                    settings,
                )

                try:
                    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
                    cls._pool = await create_pool(redis_settings)
                    log.info(f"{LogTag.STORAGE} Redis pool created successfully")
                except Exception as e:
                    log.error(
                        f"{LogTag.STORAGE} Failed to create Redis pool",
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    raise
            return cls._pool
