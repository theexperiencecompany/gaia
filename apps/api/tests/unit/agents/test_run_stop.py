"""A run's stop mark: written for its stream alone, and gone once the mark's TTL runs out."""

import fakeredis.aioredis
import pytest

from app.agents.core.background.run_stop import request_stop, stop_requested
from app.constants.cache import RUN_STOP_PREFIX, RUN_STOP_TTL

pytestmark = pytest.mark.unit


async def test_a_stop_marks_only_its_own_stream(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await request_stop("stream-1")

    assert await stop_requested("stream-1")
    assert not await stop_requested("stream-2")


async def test_a_stop_mark_expires_after_its_ttl(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await request_stop("stream-1")

    assert await fake_redis.ttl(f"{RUN_STOP_PREFIX}stream-1") == RUN_STOP_TTL
