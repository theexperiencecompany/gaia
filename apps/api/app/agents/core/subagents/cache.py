"""Bounded LRU+TTL cache for per-(integration, user) compiled subagent graphs.

Compiled LangGraph state graphs embed ``functools.partial`` closures,
bound-method references, and live Pydantic models. They are NOT pickleable —
so an in-process cache is the only viable memo. Without a bound this cache
would grow linearly with (active users × MCP integrations) and is the heaviest
unbounded growth vector on the API/worker process.

Mirrors :class:`MCPClientPool`'s design: ``OrderedDict`` LRU + ``asyncio.Lock``
+ background TTL sweeper. Eviction fires a callback so the user-scoped MCP
tool category in the registry can be dropped alongside the graph.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import inspect
from typing import TYPE_CHECKING

from app.constants.cache import (
    SUBAGENT_GRAPH_CACHE_MAX_SIZE,
    SUBAGENT_GRAPH_CACHE_TTL_SECONDS,
    SUBAGENT_GRAPH_CLEANUP_INTERVAL_SECONDS,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


CacheKey = tuple[str, str]  # (integration_id, user_id)
EvictionHandler = Callable[[str, str], None | Awaitable[None]]


@dataclass
class _PooledGraph:
    graph: CompiledStateGraph
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.last_used = datetime.now(UTC)


class UserSubagentGraphCache:
    """LRU+TTL bounded cache for per-(integration, user) compiled subagent graphs."""

    def __init__(
        self,
        max_size: int = SUBAGENT_GRAPH_CACHE_MAX_SIZE,
        ttl_seconds: int = SUBAGENT_GRAPH_CACHE_TTL_SECONDS,
    ) -> None:
        self._cache: OrderedDict[CacheKey, _PooledGraph] = OrderedDict()
        self._max_size = max_size
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._on_evict: EvictionHandler | None = None

    def set_eviction_handler(self, handler: EvictionHandler) -> None:
        """Register a callback invoked with (integration_id, user_id) on eviction.

        Used to drop the user-scoped MCP tool category from the tool registry
        when a subagent graph is evicted, so the registry doesn't accumulate
        orphaned categories.
        """
        self._on_evict = handler

    async def get(self, integration_id: str, user_id: str) -> CompiledStateGraph | None:
        """Return the cached graph, refreshing its LRU position, or None."""
        key = (integration_id, user_id)
        async with self._lock:
            pooled = self._cache.get(key)
            if pooled is None:
                return None
            pooled.touch()
            self._cache.move_to_end(key)
            return pooled.graph

    async def put(
        self, integration_id: str, user_id: str, graph: CompiledStateGraph
    ) -> None:
        """Insert or replace; evicts least-recently-used entry if at capacity."""
        key = (integration_id, user_id)
        evicted: CacheKey | None = None
        async with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                existing.graph = graph
                existing.touch()
                self._cache.move_to_end(key)
                return

            if len(self._cache) >= self._max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                evicted = evicted_key

            self._cache[key] = _PooledGraph(graph=graph)

        if evicted is not None:
            await self._fire_eviction(*evicted)

    async def invalidate(self, integration_id: str, user_id: str | None = None) -> None:
        """Drop entries for an integration, optionally scoped to a single user."""
        dropped: list[CacheKey] = []
        async with self._lock:
            if user_id is not None:
                if (integration_id, user_id) in self._cache:
                    del self._cache[(integration_id, user_id)]
                    dropped.append((integration_id, user_id))
            else:
                for k in list(self._cache.keys()):
                    if k[0] == integration_id:
                        del self._cache[k]
                        dropped.append(k)

        for k in dropped:
            await self._fire_eviction(*k)

    async def cleanup_stale(self) -> None:
        """Remove entries that haven't been used within TTL."""
        stale: list[CacheKey] = []
        async with self._lock:
            now = datetime.now(UTC)
            for k, pooled in list(self._cache.items()):
                if now - pooled.last_used > self._ttl:
                    del self._cache[k]
                    stale.append(k)
        if stale:
            log.info(
                f"UserSubagentGraphCache evicted {len(stale)} stale entries "
                f"(size={len(self._cache)}/{self._max_size})"
            )
        for k in stale:
            await self._fire_eviction(*k)

    async def _fire_eviction(self, integration_id: str, user_id: str) -> None:
        if self._on_evict is None:
            return
        try:
            result = self._on_evict(integration_id, user_id)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            log.warning(
                f"Subagent cache eviction handler failed for "
                f"({integration_id}, {user_id}): {e}"
            )

    async def start_cleanup_loop(
        self, interval: int = SUBAGENT_GRAPH_CLEANUP_INTERVAL_SECONDS
    ) -> None:
        """Start the background TTL sweeper. Idempotent."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    log.info("UserSubagentGraphCache cleanup loop cancelled")
                    raise
                try:
                    await self.cleanup_stale()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"Error in subagent cache cleanup loop: {e}")

        self._cleanup_task = asyncio.create_task(_loop())
        log.info("UserSubagentGraphCache cleanup loop started")

    async def shutdown(self) -> None:
        """Cancel the cleanup task and clear all entries."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        async with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


@lazy_provider(
    name="user_subagent_graph_cache",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def init_user_subagent_graph_cache() -> UserSubagentGraphCache:
    """Initialize the cache and wire its eviction handler to the tool registry."""
    cache = UserSubagentGraphCache()

    async def _on_evict(integration_id: str, user_id: str) -> None:
        # Late import: registry indirectly loads heavy modules; deferring it
        # here keeps cache.py importable without pulling the tool stack.
        from app.agents.tools.core.registry import (  # noqa: PLC0415
            get_tool_registry,
        )

        registry = await get_tool_registry()
        registry.remove_user_mcp_category(integration_id, user_id)

    cache.set_eviction_handler(_on_evict)
    await cache.start_cleanup_loop()
    return cache


async def get_user_subagent_graph_cache() -> UserSubagentGraphCache:
    """Resolve the cache from the lazy provider registry."""
    cache = await providers.aget("user_subagent_graph_cache")
    if cache is None:
        raise RuntimeError("UserSubagentGraphCache provider not available")
    return cache
