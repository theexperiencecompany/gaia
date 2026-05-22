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
from app.workers.metrics import start_metrics_server  # noqa: E402
from shared.py.wide_events import log  # noqa: E402

# Set up common warning filters
setup_warnings()


async def startup(ctx: dict):
    """ARQ worker startup function with eager initialization."""

    log.info("ARQ worker starting up...")
    # Store startup time for monitoring/debugging
    ctx["startup_time"] = asyncio.get_event_loop().time()

    # Expose Prometheus metrics for task duration histograms. Prometheus scrapes
    # this endpoint via the `arq_worker` job.
    metrics_port = int(os.getenv("ARQ_METRICS_PORT", "9100"))
    try:
        start_metrics_server(metrics_port)
        log.info("arq_worker_metrics_server_started", port=metrics_port)
    except OSError as exc:
        log.warning("arq_worker_metrics_server_failed", port=metrics_port, error=str(exc))

    # Use unified startup function - handles provider registration, eager init, and auto-init
    await unified_startup("arq_worker")
