"""Bring up the app's providers for a suite that calls app code in-process."""

from __future__ import annotations

import asyncio

# Cases run concurrently under --concurrency; only one may do the first registration.
_lock = asyncio.Lock()
_registered = False


async def ensure_app_registered() -> None:
    """Register the lazy providers and connect Mongo + Redis, once per process.

    Imports are deferred: importing app.* at suite-registration time caches
    settings and providers from before the run's own environment is loaded.
    """
    global _registered
    async with _lock:
        if _registered:
            return
        from app.core.provider_registration import register_lazy_providers
        from app.db.redis import redis_cache
        from app.helpers.lifespan_helpers import init_mongodb_async

        register_lazy_providers("arq_worker")
        await asyncio.gather(init_mongodb_async(), redis_cache.verify_connection())
        _registered = True
