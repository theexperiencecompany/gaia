"""A long run's stream keys stay alive while it emits frames, so it stays cancellable.

Redis is real (fakeredis) rather than mocked because TTL expiry *is* the
behaviour under test; a mocked client would happily report whatever the test
told it to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest

from app.constants.cache import (
    STREAM_EVENTS_PREFIX,
    STREAM_PROGRESS_PREFIX,
)
from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache

SID = "stream-long-turn"
CONV = "conv-1"
USER = "user-1"

PROGRESS_KEY = f"{STREAM_PROGRESS_PREFIX}{SID}"
EVENTS_KEY = f"{STREAM_EVENTS_PREFIX}{SID}"

#: Seconds left on the turn's keys after it has been running a while. Any value
#: below STREAM_TTL works; this one just has to be distinguishable from a refresh.
NEARLY_EXPIRED = 30


@pytest.fixture(autouse=True)
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Patch the module singleton so every layer below sees one real Redis."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.flushall()
    await client.connection_pool.disconnect()


async def _age_the_turns_keys(client: fakeredis.aioredis.FakeRedis) -> None:
    """Wind every key of a running turn down to almost-expired.

    Stands in for wall-clock time: a turn that has been running for most of
    STREAM_TTL. Real turns reach this routinely — EXECUTOR_WAIT_TIMEOUT is 30
    minutes and BASH_MAX_TIMEOUT_SECONDS is 1800, against a 5-minute STREAM_TTL.
    """
    for key in (PROGRESS_KEY, EVENTS_KEY):
        if await client.exists(key):
            await client.expire(key, NEARLY_EXPIRED)


async def _keep_streaming_from_the_executor() -> None:
    """One more frame from a long run's Redis writer, which only publishes."""
    await StreamManager.publish_chunk(SID, 'data: {"tool": "bash", "status": "running"}\n\n')


class TestStreamKeyLifetime:
    async def test_executor_frames_keep_a_long_turn_cancellable(self, fake_redis):
        """A run whose progress key expired could no longer be flagged cancelled."""
        await StreamManager.start_stream(SID, CONV, USER)
        await _age_the_turns_keys(fake_redis)

        await _keep_streaming_from_the_executor()

        assert await fake_redis.ttl(PROGRESS_KEY) > NEARLY_EXPIRED, (
            "an executor-only turn did not refresh its progress key, so once it "
            "expires cancel_stream_endpoint returns 'Stream not found' and never "
            "sets the cancel signal — the stop button silently does nothing"
        )
