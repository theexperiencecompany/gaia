"""Shared fixtures for the sandbox unit tier."""

from collections.abc import AsyncIterator
import contextlib

import pytest

from app.services.sandbox import pool as pool_module


@pytest.fixture(autouse=True)
def _no_cross_replica_lock(monkeypatch):
    """Neutralize the Redis half of the acquisition lock for the whole unit tier.

    The unit tier is hermetic and does no I/O, so it cannot take a real lease —
    and ``redis_cache.redis`` is a process-wide client bound to whichever event
    loop touched it first, which surfaces as ``Event loop is closed`` in the
    second test that reaches it.

    Only the Redis leg is stubbed. The in-process ``asyncio.Lock`` still runs, so
    these tests keep asserting on real per-user locking; the cross-replica lease
    (mutual exclusion, renewal, expiry) is proven against real Redis in
    ``tests/integration/real/test_sandbox_lock_real.py``.
    """

    @contextlib.asynccontextmanager
    async def _noop(user_id: str) -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(pool_module, "_redis_user_lock", _noop)
