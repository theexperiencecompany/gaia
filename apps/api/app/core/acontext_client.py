"""Acontext client for self-learning capabilities.

This module provides a lazy-loaded Acontext client for tracking subagent
executions and enabling skill learning from completed tasks.
"""

from typing import Optional

from acontext import AcontextClient
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers


@lazy_provider(
    name="acontext_client",
    required_keys=[settings.ACONTEXT_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Acontext client not configured. Self-learning features will be disabled.",
)
def create_acontext_client() -> AcontextClient:
    """Create and configure Acontext client.

    Returns:
        AcontextClient: Configured Acontext client instance
    """
    logger.info(
        f"Initializing Acontext client with base URL: {settings.ACONTEXT_BASE_URL}"
    )

    client = AcontextClient(
        base_url=settings.ACONTEXT_BASE_URL,
        api_key=settings.ACONTEXT_API_KEY,
    )

    # Test connection
    try:
        client.ping()
        logger.info("Acontext client initialized successfully")
    except Exception as e:
        logger.warning(f"Acontext client connection test failed: {e}")
        raise

    return client


def init_acontext_client() -> None:
    """Register Acontext client with lazy loader system."""
    create_acontext_client()
    logger.info("Acontext client registered with lazy loader")


async def get_acontext_client() -> Optional[AcontextClient]:
    """Get the Acontext client instance.

    Returns:
        Optional[AcontextClient]: Client instance if available, None otherwise
    """
    if not settings.ACONTEXT_ENABLED:
        return None

    return await providers.aget("acontext_client")
