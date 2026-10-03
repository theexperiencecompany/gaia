"""How the browser stack's API and worker processes boot: the same services in both, as production starts them.

This is unified_startup's eager half: providers registered, Mongo and Redis
verified, the outbound bot queues declared. What it leaves out is the strict
auto-initialisation of every provider, because two of those cannot run
hermetically: the triggers store embeds through Google's API over the network,
and startup validation needs a seeded plans collection. Neither is on a browser
task's path, and every provider the path does use still initialises lazily on
first use, as in production.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from arq.worker import Worker
from fastapi import FastAPI
import uvicorn

from app.config.settings import settings
from app.core.app_factory import create_app
from app.core.provider_registration import register_lazy_providers
from app.db.rabbitmq import declare_outbound_topology_on_startup
from app.db.redis import redis_cache
from app.helpers.lifespan_helpers import init_mongodb_async
from app.utils.concurrency import capture_running_loop
from app.workers.browser_worker import browser_reaper_cron, build_browser_worker
from app.workers.config.worker_settings import WorkerSettings
from shared.py.wide_events import log
from tests.integration.real.browser._stack.processes import API_READY_LINE, WORKER_READY_LINE


async def start_app_services(context: Literal["main_app", "arq_worker"]) -> None:
    """Register the providers and bring up the stores a browser task runs on."""
    settings.WORKER_TYPE = context
    capture_running_loop()
    register_lazy_providers(context)
    await init_mongodb_async()
    await redis_cache.verify_connection()
    await declare_outbound_topology_on_startup()


async def serve_browser_queue() -> None:
    """Boot the worker's services, then serve the browser queue and the main worker's browser reaper until killed.

    Production runs the reaper as one of the main worker's crons; here a main-queue
    worker with that one cron stands in for it, so a killed worker is made good.
    """
    await start_app_services("arq_worker")
    worker = build_browser_worker()
    reaper = Worker(
        functions=[],
        cron_jobs=[browser_reaper_cron()],
        redis_settings=WorkerSettings.redis_settings,
        handle_signals=False,
    )
    log.info(WORKER_READY_LINE)
    await asyncio.gather(worker.async_run(), reaper.async_run())


@asynccontextmanager
async def _api_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await start_app_services("main_app")
    log.info(API_READY_LINE)
    yield


def serve_api(port: int) -> None:
    """Serve the production app and middleware on port, booted by the stack's lifespan."""
    app = create_app()
    app.router.lifespan_context = _api_lifespan
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
