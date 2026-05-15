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
from typing import Any, Dict, Optional

from shared.py.wide_events import log
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


@dataclass
class PooledSandbox:
    """Reference to a live AsyncSandbox plus per-user concurrency primitives."""

    sandbox: Any  # e2b.AsyncSandbox — typed as Any to avoid import at module load
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refcount: int = 0
    pause_task: Optional[asyncio.Task[None]] = None
    last_canary_ts: Optional[str] = None
    # ArtifactWatcher | None — Any to avoid importing it at module load.
    watcher: Any = None


class SandboxPool:
    """Per-user in-process cache of AsyncSandbox handles."""

    def __init__(self) -> None:
        self._entries: Dict[str, PooledSandbox] = {}
        self._lock_registry: Dict[str, asyncio.Lock] = {}
        # Guards mutation of _entries and _lock_registry themselves.
        self._registry_lock = asyncio.Lock()

    async def get_lock(self, user_id: str) -> asyncio.Lock:
        """Return the per-user lock, creating it on first access."""
        async with self._registry_lock:
            lock = self._lock_registry.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._lock_registry[user_id] = lock
            return lock

    def get(self, user_id: str) -> Optional[PooledSandbox]:
        return self._entries.get(user_id)

    def put(self, user_id: str, entry: PooledSandbox) -> None:
        self._entries[user_id] = entry

    def evict(self, user_id: str) -> Optional[PooledSandbox]:
        return self._entries.pop(user_id, None)

    def all(self) -> Dict[str, PooledSandbox]:
        return dict(self._entries)


_pool_singleton: Optional[SandboxPool] = None


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
