"""
Main module for the GAIA FastAPI application.

This module initializes and runs the FastAPI application.
"""

import importlib
import time

from fastapi import FastAPI
import stackprinter

from app.config.sentry import init_sentry
from app.constants.log_tags import LogTag
from app.core.app_factory import create_app
from shared.py.wide_events import log

# Third-party patches apply on import; importlib keeps the name `app` free for the ASGI app below.
importlib.import_module("app.patches")

# Rich tracebacks for anything that escapes to the top of this process. Set
# here rather than in app/__init__.py: an excepthook is process policy, and the
# package __init__ charged stackprinter's numpy import to every importer.
stackprinter.set_excepthook(style="darkbg2")

# Create the FastAPI application
log.info(f"{LogTag.STARTUP} Starting application initialization...")
app_creation_start = time.time()
app: FastAPI = create_app()
init_sentry()

log.info(
    f"{LogTag.STARTUP} Application setup completed",
    duration_s=round(time.time() - app_creation_start, 3),
)
