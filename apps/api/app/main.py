"""
Main module for the GAIA FastAPI application.

This module initializes and runs the FastAPI application.
"""

import time

import app.patches  # noqa: F401 to apply patches
from shared.py.wide_events import log
from app.config.sentry import init_sentry
from app.core.app_factory import create_app

from fastapi import FastAPI  # noqa: F401

# Create the FastAPI application
log.set(service={"name": "gaia-api"})
log.info("Starting application initialization...")
app_creation_start = time.time()
app: FastAPI = create_app()  # type: ignore[assignment, no-redef]
init_sentry()

log.info(f"Application setup completed in {(time.time() - app_creation_start):.3f}s")
