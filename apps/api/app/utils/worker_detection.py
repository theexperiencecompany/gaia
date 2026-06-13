"""
Worker type detection utility.
"""

from app.config.settings import settings


def get_worker_type() -> str:
    """Return the current worker type ('main_app', 'arq_worker', or 'unknown')."""
    return settings.WORKER_TYPE


def is_main_app() -> bool:
    """Return True if running in the main FastAPI application."""
    return get_worker_type() == "main_app"
