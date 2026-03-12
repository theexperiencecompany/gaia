"""
ARQ worker shutdown functionality.
"""

import asyncio

from app.core.provider_registration import unified_shutdown
from shared.py.wide_events import log


async def shutdown(ctx: dict):
    """ARQ worker shutdown function with proper cleanup."""
    log.info("ARQ worker shutting down...")

    # Use unified shutdown function - handles context-aware service cleanup
    await unified_shutdown("arq_worker")

    # Show runtime statistics
    startup_time = ctx.get("startup_time", 0)
    if startup_time:
        runtime = asyncio.get_event_loop().time() - startup_time
        log.info(f"ARQ worker ran for {runtime:.2f} seconds")
