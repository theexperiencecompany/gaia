"""A turn failure must always reach the client as a non-empty message.

Found by driving a real failing turn: the OpenRouter SDK builds its exception
message as str(data.error.message) or fallback and its __str__ returns
that message verbatim, so str(exc) is genuinely "" when the provider
sends an error body with an empty message. The stream then published
{"error": ""}.

An empty string is falsy on the client, which is worse than no error handling at
all: hasError is false so no failed-response bubble renders, and
isBotMessageEmpty treats the turn as contentless, so
filterEmptyMessagePairs drops the bot message from the thread entirely. The
user sees their own message, no answer, and no explanation — exactly the
"sometimes the error just doesn't appear" report.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json

import fakeredis.aioredis
from langgraph.errors import GraphRecursionError
import pytest

from app.constants.cache import STREAM_PROGRESS_PREFIX
from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache
from app.services.chat.stream import _handle_stream_error

STREAM_ID = "stream-error-message"


@pytest.fixture(autouse=True)
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.aclose()


async def _client_frames(error: Exception) -> tuple[str, list[str]]:
    """Fail a live stream with error; return the user-facing text and what a subscriber receives."""
    await StreamManager.start_stream(STREAM_ID, "conv-1", "user-1")
    user_error = await _handle_stream_error(STREAM_ID, error)
    return user_error, [frame async for frame in StreamManager.subscribe_stream(STREAM_ID)]


class _EmptyMessageError(Exception):
    """Stands in for the SDK errors whose __str__ is empty."""

    def __str__(self) -> str:
        return ""


@pytest.mark.unit
class TestStreamErrorMessage:
    @pytest.mark.parametrize(
        "error",
        [_EmptyMessageError(), Exception(""), Exception("   ")],
        ids=["empty-str-dunder", "empty-args", "whitespace-only"],
    )
    async def test_blank_provider_error_never_reaches_the_client(self, error: Exception) -> None:
        user_error, frames = await _client_frames(error)

        assert user_error.strip(), (
            "a blank error is falsy on the client: no error bubble renders and the "
            "bot message is filtered out of the thread entirely"
        )
        error_frames = [f for f in frames if '"error"' in f]
        assert error_frames, "the failure was never published to the client"
        assert '"error": ""' not in error_frames[0]

    async def test_a_real_provider_message_is_preserved(self) -> None:
        user_error, _ = await _client_frames(Exception("Provider returned 503 Service Unavailable"))

        assert user_error == "Provider returned 503 Service Unavailable"

    async def test_recursion_limit_keeps_its_friendly_copy(self) -> None:
        user_error, _ = await _client_frames(GraphRecursionError("Recursion limit"))

        assert "step limit" in user_error


@pytest.mark.unit
class TestStreamErrorDelivery:
    @pytest.mark.regression
    async def test_a_failed_turn_reaches_the_client_as_one_error_frame(self) -> None:
        user_error, frames = await _client_frames(Exception("provider fell over"))

        error_frames = [f for f in frames if '"error"' in f]
        assert len(error_frames) == 1, frames
        assert user_error in error_frames[0]

    @pytest.mark.regression
    async def test_the_error_survives_a_progress_record_that_expired_mid_turn(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """A turn silent past STREAM_TTL loses its progress key; the real error must still reach the client."""
        await StreamManager.start_stream(STREAM_ID, "conv-1", "user-1")
        await fake_redis.delete(f"{STREAM_PROGRESS_PREFIX}{STREAM_ID}")

        user_error = await _handle_stream_error(STREAM_ID, Exception("provider timed out"))
        frames = [frame async for frame in StreamManager.subscribe_stream(STREAM_ID)]

        assert frames == [f"data: {json.dumps({'error': user_error})}\n\n"]
