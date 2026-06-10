"""
MCP Client Pool — one MCPClient per user, bounded by memory not by idle timer.

Sessions persist for the worker's lifetime. LRU eviction at the capacity cap is
the only path that closes sessions while the worker is running; under normal
load it never fires. This matches mcp_use's connection model, where the
underlying SSE/HTTP task is detached and designed to live indefinitely.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

if TYPE_CHECKING:
    from app.services.mcp.mcp_client import MCPClient


@dataclass
class PooledClient:
    """Wrapper for a pooled MCPClient."""

    client: MCPClient


class MCPClientPool:
    """Per-user MCPClient pool with LRU-only eviction at capacity."""

    def __init__(
        self,
        max_clients: int = 5000,
    ):
        self._clients: OrderedDict[str, PooledClient] = OrderedDict()
        self._max_clients = max_clients
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> MCPClient:
        """Get or create MCPClient for user."""
        evicted: PooledClient | None = None
        async with self._lock:
            if user_id in self._clients:
                pooled = self._clients[user_id]
                # Move to end (most recently used) so LRU eviction picks the
                # truly oldest entry when we hit the cap.
                self._clients.move_to_end(user_id)
                log.debug(f"Reusing pooled MCPClient for {user_id}")
                return pooled.client

            # Pop oldest if at capacity (close outside lock)
            if len(self._clients) >= self._max_clients:
                oldest_key = next(iter(self._clients))
                evicted = self._clients.pop(oldest_key)
                log.info(
                    f"MCPClientPool at capacity ({self._max_clients}); LRU-evicting {oldest_key}"
                )

            # Create new client (local import to avoid circular dependency)
            from app.services.mcp.mcp_client import MCPClient

            client = MCPClient(user_id=user_id)
            self._clients[user_id] = PooledClient(client=client)
            log.debug(f"Created new pooled MCPClient for {user_id}")

        # Close evicted sessions outside the lock to avoid blocking
        if evicted:
            try:
                await evicted.client.close_all_client_sessions()
            except Exception as e:
                log.warning(f"Error closing evicted MCP sessions: {e}")

        return client

    async def _evict(self, user_id: str):
        """Evict a client from the pool and close its connections."""
        if user_id not in self._clients:
            return

        pooled = self._clients.pop(user_id)
        try:
            await pooled.client.close_all_client_sessions()
        except Exception as e:
            log.warning(f"Error closing MCP sessions for user {user_id}: {e}")
        log.debug(f"Evicted MCPClient for {user_id}")

    async def shutdown(self):
        """Graceful shutdown of all clients."""
        async with self._lock:
            for user_id in list(self._clients.keys()):
                await self._evict(user_id)

        log.info("MCPClientPool shutdown complete")

    @property
    def size(self) -> int:
        """Current number of pooled clients."""
        return len(self._clients)


@lazy_provider(
    name="mcp_client_pool",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def init_mcp_client_pool() -> MCPClientPool:
    """Initialize the MCP client pool."""
    return MCPClientPool()


async def get_mcp_client_pool() -> MCPClientPool:
    """Get the MCP client pool from lazy provider."""
    pool = await providers.aget("mcp_client_pool")
    if pool is None:
        raise RuntimeError("MCPClientPool not available")
    return pool
