"""ARQ worker startup functionality."""

import asyncio
import os
from typing import Any

from shared.py.logging import configure_file_logging

# This is the ARQ worker, not the API — GAIA_SERVICE_NAME must match its
# Promtail label so {service="arq_worker"} agrees with the event field.
os.environ.setdefault("GAIA_SERVICE_NAME", "arq_worker")

# Rotating log files for local dev (no-op under LOG_FORMAT=json). Must run
# before any app import: provider_registration calls this first with a
# different path, and _FILE_LOGGING_CONFIGURED locks in whichever ran first.
configure_file_logging("./logs/worker")

from app.constants.log_tags import LogTag
from app.core.provider_registration import (
    setup_warnings,
    unified_startup,
)
from app.services.device.up_listener import start_up_listener
from app.utils.browser_reaper import start_browser_reaper
from app.workers.metrics import start_metrics_server
from shared.py.wide_events import log, log_context

# Set up common warning filters
setup_warnings()


async def startup(ctx: dict[str, Any]) -> None:
    """ARQ worker startup function with eager initialization.

    ARQ runs this outside any task boundary, so it gets its own: a worker that
    fails to boot (or comes up without its metrics server) is then one
    queryable worker_startup event instead of a discarded log.set.
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

        # Device socket is owned by the API pod; reply frames route back to
        # THIS process's per-pod up-channel, so the worker needs its own
        # up-listener (distinct POD_ID) or warm-connect times out on mcp.opened.
        start_up_listener()

        # Reap any crawl4ai browser drivers that escape teardown (worker crawl
        # tasks are routinely cancelled; see app/utils/browser_reaper.py).
        start_browser_reaper()
