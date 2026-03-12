"""
ARQ worker startup functionality.
"""

import asyncio
import os

from shared.py.logging import configure_file_logging

# Only write rotating log files when running outside Docker (LOG_FORMAT != json).
# In Docker, stdout JSON is captured by the Docker daemon and shipped to Loki
# via Promtail — writing to the container's ephemeral filesystem wastes disk.
# Must be called before any app imports — provider_registration transitively
# imports app.api.v1.middleware.__init__ → loggers.py, which calls
# configure_file_logging("./logs") and sets _FILE_LOGGING_CONFIGURED=True,
# making any subsequent call with a different path a no-op.
if os.getenv("LOG_FORMAT", "console") != "json":
    configure_file_logging("./logs/worker")

from app.core.provider_registration import (  # noqa: E402
    setup_warnings,
    unified_startup,
)
from shared.py.wide_events import log  # noqa: E402

# Set up common warning filters
setup_warnings()


async def startup(ctx: dict):
    """ARQ worker startup function with eager initialization."""

    log.info("ARQ worker starting up...")
    # Store startup time for monitoring/debugging
    # Store startup time for monitoring/debugging
    ctx["startup_time"] = asyncio.get_event_loop().time()

    # Use unified startup function - handles provider registration, eager init, and auto-init
    await unified_startup("arq_worker")
