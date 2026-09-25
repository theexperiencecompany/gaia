"""ARQ worker shutdown functionality."""

import asyncio
from typing import Any

from app.constants.log_tags import LogTag
from app.core.provider_registration import unified_shutdown
from app.services.device.up_listener import stop_up_listener
from app.utils.browser_reaper import stop_browser_reaper
from app.utils.crawl_obscura import shutdown_crawl_obscura
from app.workers.browser_worker import stop_browser_worker
from shared.py.wide_events import log, log_context


async def shutdown(ctx: dict[str, Any]) -> None:
    """ARQ worker shutdown function with proper cleanup.

    Own boundary for the same reason as startup: ARQ provides none, so a
    cleanup that hangs or raises would otherwise leave no event behind.
    """
    async with log_context("worker_shutdown", component="arq_lifecycle"):
        log.info(f"{LogTag.WORKER} ARQ worker shutting down...")

        # First: its jobs' cancel paths still need the services torn down below.
        await stop_browser_worker(ctx)

        await stop_browser_reaper()
        await shutdown_crawl_obscura()

        # Stop the per-pod up-listener the warm-connect path relies on (started
        # in worker startup). Symmetric with core/lifespan on the API side.
        await stop_up_listener()

        # Use unified shutdown function - handles context-aware service cleanup
        await unified_shutdown("arq_worker")

        # Show runtime statistics
        startup_time = ctx.get("startup_time", 0)
        if startup_time:
            runtime = asyncio.get_event_loop().time() - startup_time
            log.set(runtime_s=round(runtime, 2))
            log.info(f"{LogTag.WORKER} ARQ worker runtime recorded", runtime_s=round(runtime, 2))
