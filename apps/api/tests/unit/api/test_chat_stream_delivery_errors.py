"""The SSE delivery generator must never close silently on a failure.

``_stream_from_redis`` is the last hop between the background turn and the
browser. It used to catch a forwarding failure, log it, and simply return — the
client saw a well-formed stream end with no ``[DONE]`` and no error frame, which
the web client could not distinguish from a finished turn. The user got a
half-written answer that looked complete, or an empty bubble and no explanation.

A client disconnect is the one case that is NOT an error: the background task
keeps running and persists the turn, so it must stay silent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.api.v1.endpoints.chat import _stream_from_redis
from app.db.redis import redis_cache

STREAM_ID = "stream-delivery-failure"


@pytest.fixture(autouse=True)
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.aclose()


def _request(disconnected: bool = False) -> Any:
    request = AsyncMock()
    request.is_disconnected = AsyncMock(return_value=disconnected)
    return request


def _error_payloads(frames: list[str]) -> list[str]:
    """The ``error`` field of every frame that carries one."""
    errors: list[str] = []
    for frame in frames:
        body = frame.removeprefix("data: ").strip()
        if not body.startswith("{"):
            continue
        parsed = json.loads(body)
        if "error" in parsed:
            errors.append(parsed["error"])
    return errors


@pytest.mark.unit
class TestStreamDeliveryErrors:
    async def test_forwarding_failure_emits_an_error_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mid-delivery exception must reach the client as an error frame."""

        async def exploding_subscribe(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
            yield 'data: {"response":"partial"}\n\n'
            raise RuntimeError("redis connection reset")

        monkeypatch.setattr(
            "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
            exploding_subscribe,
        )

        frames = [chunk async for chunk in _stream_from_redis(STREAM_ID, _request())]

        assert _error_payloads(frames), (
            "delivery failure closed the stream with no error frame; the client "
            f"cannot tell this from a completed turn. frames={frames}"
        )

    async def test_client_disconnect_stays_silent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A disconnect is not a failure — the background task still persists."""

        async def subscribe(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
            yield 'data: {"response":"partial"}\n\n'
            yield 'data: {"response":"more"}\n\n'

        monkeypatch.setattr("app.api.v1.endpoints.chat.stream_manager.subscribe_stream", subscribe)

        frames = [
            chunk async for chunk in _stream_from_redis(STREAM_ID, _request(disconnected=True))
        ]

        assert _error_payloads(frames) == []

    async def test_cancellation_does_not_emit_an_error_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Client-cancelled delivery re-raises; it is not a turn failure."""

        async def cancelling_subscribe(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
            yield 'data: {"response":"partial"}\n\n'
            raise asyncio.CancelledError

        monkeypatch.setattr(
            "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
            cancelling_subscribe,
        )

        frames: list[str] = []

        async def drain() -> None:
            async for chunk in _stream_from_redis(STREAM_ID, _request()):
                frames.append(chunk)

        with pytest.raises(asyncio.CancelledError):
            await drain()

        assert _error_payloads(frames) == []
