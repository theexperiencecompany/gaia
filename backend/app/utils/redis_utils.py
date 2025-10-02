"""Redis utilities for GAIA system."""

import asyncio

from app.config.loggers import general_logger as logger


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
        if cls._pool is None:
            async with cls._lock:
                if cls._pool is None:
                    from app.config.settings import settings
                    from arq import create_pool
                    from arq.connections import RedisSettings

                    try:
                        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
                        cls._pool = await create_pool(redis_settings)
                        logger.info("Redis pool created successfully")
                    except Exception as e:
                        logger.error(f"Failed to create Redis pool: {e}")
                        raise
        return cls._pool

    @classmethod
    async def close_pool(cls):
        """Close the Redis pool connection."""
        if cls._pool:
            async with cls._lock:
                if cls._pool:
                    try:
                        await cls._pool.close()
                        cls._pool = None
                        logger.info("Redis pool closed")
                    except Exception as e:
                        logger.error(f"Error closing Redis pool: {e}")
                        cls._pool = None
