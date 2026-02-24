"""
Worker type detection utility.
"""

from app.config.settings import settings


def get_worker_type() -> str:
    """
    Get the current worker type from settings.

    Returns:
        'main_app', 'arq_worker', or 'unknown'
    """
    return settings.WORKER_TYPE


def is_main_app() -> bool:
    """
    Check if running in the main FastAPI application.

    Returns:
        True if running in main app, False otherwise
    """
    return get_worker_type() == "main_app"
