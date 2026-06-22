"""
Main module for the GAIA FastAPI application.

This module initializes and runs the FastAPI application.
"""

import time

from fastapi import FastAPI  # noqa: F401

from app.config.sentry import init_sentry
from app.constants.log_tags import LogTag
from app.core.app_factory import create_app
import app.patches  # noqa: F401 to apply patches
from shared.py.wide_events import log

# Create the FastAPI application
log.set(service={"name": "gaia-api"})
log.info(f"{LogTag.STARTUP} Starting application initialization...")
app_creation_start = time.time()
app: FastAPI = create_app()  # type: ignore[assignment, no-redef]
init_sentry()

log.info(
    f"{LogTag.STARTUP} Application setup completed in {(time.time() - app_creation_start):.3f}s"
)
