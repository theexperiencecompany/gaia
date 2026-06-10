"""In-process E2B sandbox pool.

The pool holds a single live `AsyncSandbox` per user_id. Reuse across tool
calls avoids reconnecting to E2B's control plane for every command. The pool
also exposes per-user `asyncio.Lock` + refcount used by the lifecycle layer to
serialize calls and time pause-on-idle correctly.

The pool is per-API-process, not cross-process. Two API replicas operating on
the same user will each hold their own AsyncSandbox handle; E2B coordinates
the underlying sandbox state. That's fine — the lifecycle layer reconciles via
the Mongo `e2b_sandboxes` doc as the source of truth for `sandbox_id`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.services.sandbox.shard_router import shard_for
from app.services.storage.metrics import set_sandbox_pool_size
from shared.py.wide_events import log


@dataclass
class PooledSandbox:
    """Reference to a live AsyncSandbox plus per-user concurrency primitives."""

    sandbox: Any  # e2b.AsyncSandbox — typed as Any to avoid import at module load
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refcount: int = 0
    pause_task: asyncio.Task[None] | None = None
    last_canary_ts: str | None = None
    # ArtifactWatcher | None — Any to avoid importing it at module load.
    watcher: Any = None


class SandboxPool:
    """Per-user in-process cache of AsyncSandbox handles."""

    def __init__(self) -> None:
        self._entries: dict[str, PooledSandbox] = {}
        self._lock_registry: dict[str, asyncio.Lock] = {}
        # Guards mutation of _entries and _lock_registry themselves.
        self._registry_lock = asyncio.Lock()
        # Shards we have ever published a count for. Tracked so transitions
        # to zero re-publish 0 explicitly (Prometheus gauges otherwise hold
        # their last positive value indefinitely).
        self._known_shards: set[int] = set()
        # Seed warm-pool gauges at zero for each configured shard so the
        # dashboard renders a flat zero line instead of "No data" until the
        # warm pool capability (sibling change e2b-perf-metrics-and-
        # improvements) actually populates entries.
        for shard in range(max(1, settings.JUICEFS_NUM_SHARDS)):
            set_sandbox_pool_size("warm", str(shard), 0)

    async def get_lock(self, user_id: str) -> asyncio.Lock:
        """Return the per-user lock, creating it on first access."""
        async with self._registry_lock:
            lock = self._lock_registry.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._lock_registry[user_id] = lock
            return lock

    def get(self, user_id: str) -> PooledSandbox | None:
        return self._entries.get(user_id)

    def put(self, user_id: str, entry: PooledSandbox) -> None:
        self._entries[user_id] = entry
        self._publish_size()

    def evict(self, user_id: str) -> PooledSandbox | None:
        removed = self._entries.pop(user_id, None)
        if removed is not None:
            self._publish_size()
        return removed

    def all(self) -> dict[str, PooledSandbox]:
        return dict(self._entries)

    def _publish_size(self) -> None:
        """Recompute per-shard pool occupancy and publish to Prometheus.

        Walks ``_entries`` once, buckets by ``shard_for(user_id)``, and emits
        one ``sandbox_pool_size{kind="user",shard=...}`` gauge value per
        shard. Re-publishes 0 for previously-seen shards now empty so the
        gauge falls instead of holding its last positive value forever.

        The walk is O(N) where N is the active user count (typically small;
        one entry per active user per replica). If this gets expensive we
        switch to incremental counts; today it's cheap.
        """
        counts: dict[int, int] = {}
        for user_id in self._entries:
            shard = shard_for(user_id)
            counts[shard] = counts.get(shard, 0) + 1
        for shard, n in counts.items():
            set_sandbox_pool_size("user", str(shard), n)
            self._known_shards.add(shard)
        for shard in self._known_shards - counts.keys():
            set_sandbox_pool_size("user", str(shard), 0)


_pool_singleton: SandboxPool | None = None


@lazy_provider(
    name="e2b_sandbox_pool",
    required_keys=[settings.E2B_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message=(
        "E2B_API_KEY is not configured. Coding tools (bash/read/write/edit) "
        "will return errors until it is set."
    ),
)
def init_sandbox_pool() -> SandboxPool:
    """Lazy-provider factory; also memoizes the module-level singleton.

    Registered with `@lazy_provider` purely to expose the E2B_API_KEY
    dependency to provider_registration. The `@lazy_provider` decorator
    wraps the return value, so callers should use `get_sandbox_pool()` to
    get the unwrapped `SandboxPool` instance.
    """
    global _pool_singleton
    if _pool_singleton is None:
        log.info("Initializing E2B sandbox pool")
        _pool_singleton = SandboxPool()
    return _pool_singleton


def get_sandbox_pool() -> SandboxPool:
    """Synchronous accessor for the SandboxPool singleton.

    The pool itself does no I/O at construction time, so we don't need the
    full `providers.aget` machinery here. Initializes on first call.
    """
    global _pool_singleton
    if _pool_singleton is None:
        log.info("Initializing E2B sandbox pool")
        _pool_singleton = SandboxPool()
    return _pool_singleton
