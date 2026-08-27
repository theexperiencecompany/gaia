from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.core.provider_registration import (
    unified_shutdown,
    unified_startup,
)
from app.services.device.revoke_listener import (
    start_revoke_listener,
    stop_revoke_listener,
)
from app.services.device.up_listener import start_up_listener, stop_up_listener
from app.utils.browser_reaper import start_browser_reaper, stop_browser_reaper
from app.utils.context_utils import _CONTEXT_EXECUTOR
from shared.py.wide_events import log, log_context


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager with lazy providers.
    Handles startup and shutdown events.

    Boot runs inside its own boundary so a failed start is one queryable
    ``api_startup`` event (which service, how long it got, which exception)
    instead of a discarded ``log.set``. The boundary covers startup only — it
    must not span the yield, or the pod would emit a single event at exit.
    """
    posthog_client = None
    try:
        async with log_context("api_startup", component="lifespan"):
            if not settings.POSTHOG_PROJECT_TOKEN or not settings.POSTHOG_HOST:
                missing_var = (
                    "POSTHOG_PROJECT_TOKEN"
                    if not settings.POSTHOG_PROJECT_TOKEN
                    else "POSTHOG_HOST"
                )
                # Never block boot: token-less environments (local dev without
                # Infisical, the schemathesis live server) legitimately run
                # without analytics — the SILENT loader no-ops captures. Make
                # the gap loud in the log instead of taking the API down.
                log.error(
                    f"{LogTag.STARTUP} PostHog not configured — analytics captures will no-op",
                    missing_var=missing_var,
                )
            await unified_startup("main_app")
            if settings.POSTHOG_PROJECT_TOKEN and settings.POSTHOG_HOST:
                posthog_client = providers.get("posthog")
            start_browser_reaper()
            start_revoke_listener()
            start_up_listener()
        yield

    except Exception as e:
        raise RuntimeError("Startup failed") from e

    finally:
        await stop_up_listener()
        await stop_revoke_listener()
        await stop_browser_reaper()
        if posthog_client is not None:
            # shutdown(), not flush(): it flushes the queue AND joins the
            # consumer threads, stops the feature-flag poller, and closes
            # exception capture. flush() alone leaves those running, and an
            # atexit hook would only fire at process exit — too late for a
            # reload or a lifespan that ends while the process lives on.
            posthog_client.shutdown()
        await unified_shutdown("main_app")
        _CONTEXT_EXECUTOR.shutdown(wait=False)
