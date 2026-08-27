"""A turn failure must always reach the client as a non-empty message.

Found by driving a real failing turn: the OpenRouter SDK builds its exception
message as ``str(data.error.message) or fallback`` and its ``__str__`` returns
that message verbatim, so ``str(exc)`` is genuinely ``""`` when the provider
sends an error body with an empty message. The stream then published
``{"error": ""}``.

An empty string is falsy on the client, which is worse than no error handling at
all: ``hasError`` is false so no failed-response bubble renders, and
``isBotMessageEmpty`` treats the turn as contentless, so
``filterEmptyMessagePairs`` drops the bot message from the thread entirely. The
user sees their own message, no answer, and no explanation — exactly the
"sometimes the error just doesn't appear" report.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import fakeredis.aioredis
from langgraph.errors import GraphRecursionError
import pytest

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


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture what the client would receive, in order."""
    chunks: list[str] = []

    async def capture(_stream_id: str, chunk: str) -> None:
        chunks.append(chunk)

    monkeypatch.setattr(
        "app.services.chat.stream.stream_manager.publish_chunk", AsyncMock(side_effect=capture)
    )
    monkeypatch.setattr(
        "app.services.chat.stream.stream_manager.set_error", AsyncMock(return_value=None)
    )
    return chunks


class _EmptyMessageError(Exception):
    """Stands in for the SDK errors whose ``__str__`` is empty."""

    def __str__(self) -> str:
        return ""


@pytest.mark.unit
class TestStreamErrorMessage:
    @pytest.mark.parametrize(
        "error",
        [_EmptyMessageError(), Exception(""), Exception("   ")],
        ids=["empty-str-dunder", "empty-args", "whitespace-only"],
    )
    async def test_blank_provider_error_never_reaches_the_client(
        self, error: Exception, published: list[str]
    ) -> None:
        user_error = await _handle_stream_error(STREAM_ID, error)

        assert user_error.strip(), (
            "a blank error is falsy on the client: no error bubble renders and the "
            "bot message is filtered out of the thread entirely"
        )
        assert published, "the failure was never published to the client"
        assert '"error": ""' not in published[0]

    async def test_a_real_provider_message_is_preserved(self, published: list[str]) -> None:
        user_error = await _handle_stream_error(
            STREAM_ID, Exception("Provider returned 503 Service Unavailable")
        )

        assert user_error == "Provider returned 503 Service Unavailable"

    async def test_recursion_limit_keeps_its_friendly_copy(self, published: list[str]) -> None:
        user_error = await _handle_stream_error(STREAM_ID, GraphRecursionError("Recursion limit"))

        assert "step limit" in user_error
