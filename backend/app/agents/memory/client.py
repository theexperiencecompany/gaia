"""Centralized Zep client management for memory and knowledge graph operations."""

from typing import Optional

from zep_cloud.client import Zep

from app.config.loggers import llm_logger as logger
from app.config.settings import settings


class ZepClientManager:
    """Manages Zep client lifecycle and configuration."""

    def __init__(self):
        self._client: Optional[Zep] = None

    def get_client(self) -> Zep:
        """
        Get the properly configured Zep client instance.

        Returns:
            Configured Zep client
        """
        if self._client is None:
            if not settings.ZEP_API_KEY:
                raise ValueError("ZEP_API_KEY is required but not set")

            self._client = Zep(api_key=settings.ZEP_API_KEY)
            logger.info("Zep client initialized successfully")

        return self._client

    def reset(self):
        """Reset the client instance (useful for testing)."""
        self._client = None
        logger.info("Zep client reset")


# Global instance
zep_client_manager = ZepClientManager()
