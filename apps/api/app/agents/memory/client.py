"""Centralized memory client management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.settings import settings

if TYPE_CHECKING:
    from mem0 import AsyncMemoryClient


class MemoryClientManager:
    """Manages memory client lifecycle and configuration."""

    def __init__(self) -> None:
        self._client: AsyncMemoryClient | None = None
        self._graph_enabled: bool = False

    async def get_client(self) -> AsyncMemoryClient:
        """Get the properly configured memory client instance with graph memory enabled."""
        # Lazy import: mem0 pulls litellm (~200MB). Load only when memory is first used.
        from mem0 import AsyncMemoryClient

        if self._client is None:
            client = AsyncMemoryClient(
                api_key=settings.MEM0_API_KEY,
                org_id=settings.MEM0_ORG_ID,
                project_id=settings.MEM0_PROJECT_ID,
            )

            # Enable graph memory in project settings
            if not self._graph_enabled:
                try:
                    await client.project.update(enable_graph=True)
                    self._graph_enabled = True
                except Exception as e:
                    # Log but don't fail if graph setup fails
                    print(f"Warning: Could not enable graph memory: {e}")

            self._client = client

        return self._client

    def reset(self) -> None:
        """Reset the client instance (useful for testing)."""
        self._client = None


# Global instance
memory_client_manager = MemoryClientManager()
