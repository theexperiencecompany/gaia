"""``StreamManager.has_events`` — the "is there anything left to replay?" probe.

``GET /stream/{id}`` short-circuits a finished stream to a bare ``[DONE]`` only
when this returns False. Answering False while the event log still holds frames
drops them all — that is the bug the probe exists to prevent (a HIL resume
publishes its second approval card and closes within ~100ms, well before the
client re-attaches). Answering True after the log has expired is just as bad in
the other direction: ``subscribe_stream`` then idles on keepalives forever.

Redis is real (fakeredis) rather than mocked, because key existence and TTL
expiry *are* the behaviour under test; a mocked client would report whatever the
test told it to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest

from app.constants.cache import STREAM_EVENTS_PREFIX
from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache

pytestmark = pytest.mark.unit

SID = "stream-has-events"
CONV = "conv-1"
USER = "user-1"

EVENTS_KEY = f"{STREAM_EVENTS_PREFIX}{SID}"

APPROVAL_FRAME = (
    'data: {"tool_data": {"tool_name": "approval_request", "data": {"approval_id": "a2"}}}\n\n'
)


@pytest.fixture
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Patch the module singleton so StreamManager runs against one real Redis."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.flushall()
    await client.connection_pool.disconnect()


class TestHasEvents:
    async def test_false_before_anything_is_published(self, fake_redis) -> None:
        await StreamManager.start_stream(SID, CONV, USER)

        assert await StreamManager.has_events(SID) is False

    async def test_true_once_a_frame_is_published(self, fake_redis) -> None:
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.publish_chunk(SID, APPROVAL_FRAME)

        assert await StreamManager.has_events(SID) is True

    @pytest.mark.regression
    async def test_true_after_completion_while_the_log_survives(self, fake_redis) -> None:
        """A completed stream still has frames to replay.

        The short-circuit reads this to decide between replaying the log and
        answering a bare ``[DONE]``. A resumed HIL turn publishes its second
        approval card and completes before the client re-attaches, so False here
        means the user never sees the card.
        """
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.publish_chunk(SID, APPROVAL_FRAME)
        await StreamManager.complete_stream(SID)

        assert await StreamManager.has_events(SID) is True

    async def test_false_once_the_log_has_expired(self, fake_redis) -> None:
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.publish_chunk(SID, APPROVAL_FRAME)
        await StreamManager.complete_stream(SID)

        await fake_redis.delete(EVENTS_KEY)

        assert await StreamManager.has_events(SID) is False

    async def test_false_for_a_stream_id_that_never_existed(self, fake_redis) -> None:
        assert await StreamManager.has_events("never-started") is False

    async def test_scoped_to_the_stream_id(self, fake_redis) -> None:
        await StreamManager.start_stream(SID, CONV, USER)
        await StreamManager.publish_chunk(SID, APPROVAL_FRAME)

        assert await StreamManager.has_events(f"{SID}-other") is False

    async def test_false_when_redis_is_unavailable(self, monkeypatch) -> None:
        """Startup order and a dropped connection both leave the singleton unset;
        the probe must answer False rather than raise into the SSE handler."""
        monkeypatch.setattr(redis_cache, "redis", None)

        assert await StreamManager.has_events(SID) is False
