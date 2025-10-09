from contextlib import asynccontextmanager

from app.config.loggers import app_logger as logger
from app.core.provider_registration import (
    unified_shutdown,
    unified_startup,
)
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager with lazy providers.
    Handles startup and shutdown events.
    """
    try:
        await unified_startup("main_app")
        yield

    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise RuntimeError("Startup failed") from e

    finally:
        await unified_shutdown("main_app")
