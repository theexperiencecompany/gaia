"""Shared seams for the sandbox unit tests.

Two independent autouse seams, one per credential and lock boundary, so the
tier runs without Mongo or Redis. The lifecycle resolved-key seam is what every
E2B decision reads; it defaults to a resolvable key (the hosted posture) and
missing-key tests rebind it per case. The pool redis-lock leg is neutralized
to stay single-process while the in-process asyncio lock is still exercised.
"""

from collections.abc import AsyncIterator
import contextlib
from unittest.mock import AsyncMock

import pytest

from app.services.sandbox import lifecycle, pool as pool_module


@pytest.fixture(autouse=True)
def _e2b_key_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="test-e2b-key"))


@pytest.fixture(autouse=True)
def _no_cross_replica_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the Redis half of the acquisition lock for the whole unit tier.

    redis_cache.redis is a process-wide client bound to whichever event loop
    touched it first, surfacing as "Event loop is closed" in the second unit
    test.
    """

    @contextlib.asynccontextmanager
    async def _noop(user_id: str) -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(pool_module, "_redis_user_lock", _noop)
