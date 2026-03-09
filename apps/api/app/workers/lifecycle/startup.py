"""
ARQ worker startup functionality.
"""

import asyncio

from app.core.provider_registration import (
    setup_warnings,
    unified_startup,
)
from shared.py.logging import configure_file_logging
from shared.py.wide_events import log

# Set up common warning filters
setup_warnings()

# Write structured JSON log files for Promtail to scrape in local dev.
# Uses a separate directory from the API so Promtail can label them distinctly.
configure_file_logging("./logs/worker")


async def startup(ctx: dict):
    """ARQ worker startup function with eager initialization."""

    log.info("ARQ worker starting up...")
    # Store startup time for monitoring/debugging
    # Store startup time for monitoring/debugging
    ctx["startup_time"] = asyncio.get_event_loop().time()

    # Use unified startup function - handles provider registration, eager init, and auto-init
    await unified_startup("arq_worker")
