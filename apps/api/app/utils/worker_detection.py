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


def is_arq_worker() -> bool:
    """
    Check if running in ARQ worker.

    Returns:
        True if running in ARQ worker, False otherwise
    """
    return get_worker_type() == "arq_worker"


def has_websocket_pool() -> bool:
    """
    Check if the current process has access to WebSocket connections.
    Only the main app has WebSocket connections.

    Returns:
        True if has WebSocket pool, False otherwise
    """
    return is_main_app()
