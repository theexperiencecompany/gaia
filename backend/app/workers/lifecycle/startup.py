"""
ARQ worker startup functionality.
"""

import asyncio

from app.agents.core.graph_builder.build_graph import build_graph
from app.agents.core.graph_manager import GraphManager
from app.config.loggers import arq_worker_logger as logger
from app.core.provider_registration import (
    unified_startup,
    setup_warnings,
)

# Set up common warning filters
setup_warnings()


async def startup(ctx: dict):
    """ARQ worker startup function with eager initialization."""

    logger.info("ARQ worker starting up...")
    # Store startup time for monitoring/debugging
    # Store startup time for monitoring/debugging
    ctx["startup_time"] = asyncio.get_event_loop().time()

    # Use unified startup function - handles provider registration, eager init, and auto-init
    await unified_startup("arq_worker")
