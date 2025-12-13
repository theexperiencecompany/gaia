"""
Main module for the GAIA FastAPI application.

This module initializes and runs the FastAPI application.
"""

import time

from app.config.loggers import app_logger as logger
from app.config.sentry import init_sentry
from app.core.app_factory import create_app

# Create the FastAPI application
logger.info("Starting application initialization...")
app_creation_start = time.time()
app = create_app()
init_sentry()

logger.info(f"Application setup completed in {(time.time() - app_creation_start):.3f}s")
