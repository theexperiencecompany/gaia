from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.provider_registration import (
    unified_shutdown,
    unified_startup,
)
from app.utils.context_utils import _CONTEXT_EXECUTOR
from shared.py.wide_events import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager with lazy providers.
    Handles startup and shutdown events.
    """
    try:
        log.set(startup={"service": "gaia-api"})
        await unified_startup("main_app")
        yield

    except Exception as e:
        log.error(f"Error during startup: {e}")
        raise RuntimeError("Startup failed") from e

    finally:
        await unified_shutdown("main_app")
        _CONTEXT_EXECUTOR.shutdown(wait=False)
