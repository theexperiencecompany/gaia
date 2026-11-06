"""Regression for #1618: a module-scoped redis_cache patch reaches every test in its module.

The browser stack tier boots one stack per module and points redis_cache at that
stack's database on the module's loop; a per-test override replaced it, so every
scenario read job state from the wrong database on the wrong loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.config.settings import settings
from app.db.redis import redis_cache
from tests.helpers import worker_redis_url

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(
        worker_redis_url(settings.REDIS_URL or "redis://localhost:6379/0"), decode_responses=True
    )
    patches = pytest.MonkeyPatch()
    patches.setattr(redis_cache, "redis", client)
    yield client
    patches.undo()
    await client.aclose()


@pytest.mark.parametrize("attempt", [1, 2])
async def test_redis_cache_reads_the_database_the_module_pointed_it_at(
    module_redis: Redis, attempt: int
) -> None:
    key = f"module-redis-patch-{attempt}-{uuid.uuid4().hex}"
    await module_redis.set(key, '"from the module client"', ex=60)

    assert await redis_cache.get(key) == "from the module client"
