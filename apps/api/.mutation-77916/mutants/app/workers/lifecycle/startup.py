"""
ARQ worker startup functionality.
"""

import asyncio
import os
from typing import Any

from shared.py.logging import configure_file_logging

# Rotating log files for local development; a no-op under LOG_FORMAT=json,
# where stdout NDJSON is shipped to Loki instead (see configure_file_logging).
# Must be called before any app imports — provider_registration transitively
# imports app.api.v1.middleware.__init__ → loggers.py, which calls
# configure_file_logging("./logs") and sets _FILE_LOGGING_CONFIGURED=True,
# making any subsequent call with a different path a no-op.
# This process is the ARQ worker, not the API. GAIA_SERVICE_NAME must equal
# its Promtail label so the in-event `service` field and {service="arq_worker"}
# agree; setdefault so an explicit env var still wins.
os.environ.setdefault("GAIA_SERVICE_NAME", "arq_worker")

configure_file_logging("./logs/worker")

from app.constants.log_tags import LogTag
from app.core.provider_registration import (
    setup_warnings,
    unified_startup,
)
from app.utils.browser_reaper import start_browser_reaper
from app.workers.metrics import start_metrics_server
from shared.py.wide_events import log, log_context

# Set up common warning filters
setup_warnings()


async def startup(ctx: dict[str, Any]) -> None:
    """ARQ worker startup function with eager initialization.

    ARQ runs this outside any task boundary, so it gets its own: a worker that
    fails to boot (or comes up without its metrics server) is then one
    queryable ``worker_startup`` event instead of a discarded ``log.set``.
    """

    async with log_context("worker_startup", component="arq_lifecycle"):
        log.info(f"{LogTag.WORKER} ARQ worker starting up...")
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

        # Reap any crawl4ai browser drivers that escape teardown (worker crawl
        # tasks are routinely cancelled; see app/utils/browser_reaper.py).
        start_browser_reaper()
