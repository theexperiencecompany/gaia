"""Shared fixtures for the sandbox unit tier."""

from collections.abc import AsyncIterator
import contextlib

import pytest

from app.services.sandbox import pool as pool_module


@pytest.fixture(autouse=True)
def _no_cross_replica_lock(monkeypatch):
    """Neutralize the Redis half of the acquisition lock for the whole unit tier.

    redis_cache.redis is a process-wide client bound to whichever event loop
    touched it first, surfacing as "Event loop is closed" in the second unit
    test. Only the Redis leg is stubbed — the cross-replica lease is proven
    against real Redis in tests/integration/real/test_sandbox_lock_real.py.
    """

    @contextlib.asynccontextmanager
    async def _noop(user_id: str) -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(pool_module, "_redis_user_lock", _noop)
