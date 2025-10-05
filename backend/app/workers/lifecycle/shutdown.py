"""
ARQ worker shutdown functionality.
"""

import asyncio

from app.config.loggers import arq_worker_logger as logger
from app.core.provider_registration import unified_shutdown


async def shutdown(ctx: dict):
    """ARQ worker shutdown function with proper cleanup."""
    logger.info("ARQ worker shutting down...")

    # Use unified shutdown function - handles context-aware service cleanup
    await unified_shutdown("arq_worker")

    # Show runtime statistics
    startup_time = ctx.get("startup_time", 0)
    if startup_time:
        runtime = asyncio.get_event_loop().time() - startup_time
        logger.info(f"ARQ worker ran for {runtime:.2f} seconds")
