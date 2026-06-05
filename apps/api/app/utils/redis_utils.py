"""Redis utilities for GAIA system."""

import asyncio

from shared.py.wide_events import log


class RedisPoolManager:
    """Thread-safe singleton Redis pool manager."""

    _instance = None
    _lock = asyncio.Lock()
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_pool(cls):
        """Get or create Redis pool."""
        log.set(operation="redis_get_pool", component="RedisPoolManager")
        if cls._pool is None:
            async with cls._lock:
                if cls._pool is None:
                    from arq import create_pool
                    from arq.connections import RedisSettings

                    from app.config.settings import settings

                    try:
                        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
                        cls._pool = await create_pool(redis_settings)
                        log.info("Redis pool created successfully")
                    except Exception as e:
                        log.error(f"Failed to create Redis pool: {e}")
                        raise
        return cls._pool
