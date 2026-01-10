"""
MCP Client Pool - Thread-safe pool for per-user MCPClient instances.

Uses LRU eviction and TTL-based cleanup to manage memory.
Integrated with lazy_provider for proper lifecycle management.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.config.loggers import langchain_logger as logger
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers

if TYPE_CHECKING:
    from app.services.mcp.mcp_client import MCPClient


@dataclass
class PooledClient:
    """Wrapper for pooled MCPClient with metadata."""

    client: "MCPClient"
    last_used: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self):
        """Update last used timestamp."""
        self.last_used = datetime.now(timezone.utc)


class MCPClientPool:
    """
    Thread-safe MCP client pool with LRU eviction.

    Features:
    - Reuses MCPClient instances for the same user across requests
    - LRU eviction when pool reaches max capacity
    - Background cleanup of stale clients (not used within TTL)
    - Graceful shutdown of all connections
    """

    def __init__(
        self,
        max_clients: int = 100,
        ttl_seconds: int = 300,  # 5 minutes
    ):
        self._clients: OrderedDict[str, PooledClient] = OrderedDict()
        self._max_clients = max_clients
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def get(self, user_id: str) -> "MCPClient":
        """Get or create MCPClient for user."""
        # Import here to avoid circular import
        from app.services.mcp.mcp_client import MCPClient

        async with self._lock:
            if user_id in self._clients:
                pooled = self._clients[user_id]
                pooled.touch()
                # Move to end (most recently used)
                self._clients.move_to_end(user_id)
                logger.debug(f"Reusing pooled MCPClient for {user_id}")
                return pooled.client

            # Evict oldest if at capacity
            if len(self._clients) >= self._max_clients:
                oldest_key = next(iter(self._clients))
                await self._evict(oldest_key)

            # Create new client
            client = MCPClient(user_id=user_id)
            self._clients[user_id] = PooledClient(client=client)
            logger.debug(f"Created new pooled MCPClient for {user_id}")
            return client

    async def _evict(self, user_id: str):
        """Evict a client from the pool and close its connections."""
        if user_id not in self._clients:
            return

        pooled = self._clients.pop(user_id)
        # Close all active MCP sessions
        for integration_id in list(pooled.client._clients.keys()):
            try:
                await pooled.client._clients[integration_id].close_all_sessions()
            except Exception as e:
                logger.warning(f"Error closing MCP session for {integration_id}: {e}")
        logger.debug(f"Evicted MCPClient for {user_id}")

    async def cleanup_stale(self):
        """Remove clients that haven't been used within TTL."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            stale = [
                uid
                for uid, pooled in self._clients.items()
                if now - pooled.last_used > self._ttl
            ]
            for user_id in stale:
                await self._evict(user_id)
            if stale:
                logger.info(f"Cleaned up {len(stale)} stale MCP clients")

    async def start_cleanup_loop(self, interval: int = 60):
        """Start background cleanup task."""

        async def _loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.cleanup_stale()
                except Exception as e:
                    logger.warning(f"Error in MCP cleanup loop: {e}")

        self._cleanup_task = asyncio.create_task(_loop())
        logger.info("MCPClientPool cleanup loop started")

    async def shutdown(self):
        """Graceful shutdown of all clients."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for user_id in list(self._clients.keys()):
                await self._evict(user_id)

        logger.info("MCPClientPool shutdown complete")

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
    pool = MCPClientPool()
    await pool.start_cleanup_loop()
    return pool


async def get_mcp_client_pool() -> MCPClientPool:
    """Get the MCP client pool from lazy provider."""
    pool = await providers.aget("mcp_client_pool")
    if pool is None:
        raise RuntimeError("MCPClientPool not available")
    return pool
