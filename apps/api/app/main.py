"""
Main module for the GAIA FastAPI application.

This module initializes and runs the FastAPI application.
"""

import time

from fastapi import FastAPI

from app.config.sentry import init_sentry
from app.constants.log_tags import LogTag
from app.core.app_factory import create_app
import app.patches
from shared.py.wide_events import log

# Create the FastAPI application
log.info(f"{LogTag.STARTUP} Starting application initialization...")
app_creation_start = time.time()
app: FastAPI = create_app()  # type: ignore[no-redef]  # `import app.patches` above binds the package name; this rebinds it to the ASGI app
init_sentry()

log.info(
    f"{LogTag.STARTUP} Application setup completed",
    duration_s=round(time.time() - app_creation_start, 3),
)
