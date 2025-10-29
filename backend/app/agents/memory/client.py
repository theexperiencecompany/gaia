"""Centralized memory client management."""

from typing import Optional

from mem0 import AsyncMemoryClient

from app.config.settings import settings


class MemoryClientManager:
    """Manages memory client lifecycle and configuration."""

    def __init__(self):
        self._client: Optional[AsyncMemoryClient] = None

    async def get_client(self) -> AsyncMemoryClient:
        """Get the properly configured memory client instance."""
        if self._client is None:
            client = AsyncMemoryClient(
                api_key=settings.MEM0_API_KEY,
                org_id=settings.MEM0_ORG_ID,
                project_id=settings.MEM0_PROJECT_ID,
            )
            # Configure the project with graph enabled

            if client.project:
                await client.project.update(enable_graph=True)

            self._client = client

        return self._client

    def reset(self):
        """Reset the client instance (useful for testing)."""
        self._client = None


# Global instance
memory_client_manager = MemoryClientManager()
