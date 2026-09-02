"""Stress: SSE resume-from-cursor and mid-stream cancellation.

Real code under test:
1. ``StreamManager.subscribe_stream`` (``app/core/stream_manager.py``) — the
   cursor/resume mechanism: every frame carries an ``id:`` line (the Redis
   Stream entry id) and ``subscribe_executor_stream`` reconnects with
   ``Last-Event-ID``, so a reloaded client replays only what it missed.
   Redis Streams are an in-process fake with cursor-ordered xadd/xread.
2. The per-chunk cancellation loop of ``execute_graph_streaming``
   (``app/helpers/agent_helpers.py``) — the graph driver checks
   ``stream_manager.is_cancelled(stream_id)`` before every event, so flipping
   the flag mid-stream must stop production, emit the ``cancelled`` nostream
   marker, and record the interruption once.
"""

import asyncio
from collections.abc import AsyncGenerator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.cache import STREAM_TTL
from app.constants.streaming import STREAM_DONE_SIGNAL
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.helpers.agent_helpers import execute_graph_streaming

pytestmark = pytest.mark.stress

STREAM_ID = "stream-stress-001"


class _FakeStreamsRedis:
    """In-process Redis stand-in mirroring the client contract.

    Streams are an ordered list of ``(entry_id, fields)`` per key with
    monotonic ids ("0-1", "0-2", ...) exactly like the real thing, so the
    xread-after-cursor semantics and the SSE ``id:`` cursor lines round-trip.
    Plain keys hold raw JSON strings, matching RedisCache's
    serialize/deserialize round-trip.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._keys: dict[str, str] = {}
        self._seq = 0

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self._seq += 1
        entry_id = f"0-{self._seq}"
        self._streams.setdefault(name, []).append((entry_id, dict(fields)))
        return entry_id

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        result: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for name, cursor in streams.items():
            entries = self._streams.get(name, [])
            if cursor == "0-0":
                start = 0
            else:
                ids = [entry_id for entry_id, _ in entries]
                start = ids.index(cursor) + 1 if cursor in ids else len(entries)
            tail = entries[start:]
            if count:
                tail = tail[:count]
            if tail:
                result.append((name, tail))
        return result

    async def expire(self, name: str, time: int) -> bool:
        return name in self._keys or name in self._streams

    async def ttl(self, name: str) -> int:
        """Full TTL for a live key, -2 for a missing one.

        This fake has no clock, so keys never age. publish_chunk's liveness
        refresh reads this to decide whether to re-expire the turn's keys; a
        full TTL means "plenty of headroom" and it returns early, leaving these
        resume-cursor tests to exercise only the stream semantics they are about.
        """
        if name in self._keys or name in self._streams:
            return STREAM_TTL
        return -2

    async def get(self, name: str) -> str | None:
        return self._keys.get(name)

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and name in self._keys:
            return None
        self._keys[name] = value
        return True

    async def setex(self, name: str, time: int, value: str) -> bool:
        self._keys[name] = value
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            removed += self._keys.pop(name, None) is not None
            removed += self._streams.pop(name, None) is not None
        return removed


class _FakeGraph:
    """A CompiledAgentGraph stand-in whose astream() yields custom events.

    Mirrors the real driver contract: one event per "model emission", with the
    event loop yielded between emissions so a concurrent cancel can land
    mid-stream.
    """

    def __init__(self, total_events: int) -> None:
        self.total_events = total_events
        self.pulled = 0

    def astream(self, *args: Any, **kwargs: Any) -> Any:
        async def gen() -> AsyncGenerator[tuple[Any, ...], None]:
            for i in range(self.total_events):
                self.pulled += 1
                yield ("custom", {"t": i})
                await asyncio.sleep(0)

        return gen()


async def _publish_full_stream(fake: _FakeStreamsRedis) -> None:
    """Publish three chunks then the DONE signal, so a subscriber terminates."""
    with patch.object(redis_cache, "redis", fake):
        await stream_manager.publish_chunk(STREAM_ID, "data: chunk-1\n\n")
        await stream_manager.publish_chunk(STREAM_ID, "data: chunk-2\n\n")
        await stream_manager.publish_chunk(STREAM_ID, "data: chunk-3\n\n")
        await stream_manager.publish_chunk(STREAM_ID, STREAM_DONE_SIGNAL)


class TestStreamResumeFromCursor:
    async def test_resume_from_cursor_replays_only_new_events(self):
        """A client that reconnects with Last-Event-ID (the ``id:`` line of the
        last frame it saw) must receive exactly the frames it missed — never a
        redelivery, never a gap."""
        fake = _FakeStreamsRedis()
        await _publish_full_stream(fake)

        with patch.object(redis_cache, "redis", fake):
            full = [frame async for frame in stream_manager.subscribe_stream(STREAM_ID)]

        assert full == [
            "id: 0-1\ndata: chunk-1\n\n",
            "id: 0-2\ndata: chunk-2\n\n",
            "id: 0-3\ndata: chunk-3\n\n",
        ]

        # A client that saw chunk-2 reconnects with its id as Last-Event-ID.
        fake = _FakeStreamsRedis()
        await _publish_full_stream(fake)

        with patch.object(redis_cache, "redis", fake):
            resumed = [
                frame
                async for frame in stream_manager.subscribe_stream(STREAM_ID, last_event_id="0-2")
            ]

        assert resumed == ["id: 0-3\ndata: chunk-3\n\n"]

    async def test_cancel_flag_flips_and_subscribers_terminate_on_cancelled_signal(self):
        """cancel_stream sets the flag the producer checks per chunk, and the
        CANCELLED log entry ends a subscriber with [DONE] instead of hanging."""
        fake = _FakeStreamsRedis()
        with patch.object(redis_cache, "redis", fake):
            assert await stream_manager.is_cancelled(STREAM_ID) is False

            await stream_manager.cancel_stream(STREAM_ID)

            assert await stream_manager.is_cancelled(STREAM_ID) is True
            frames = [frame async for frame in stream_manager.subscribe_stream(STREAM_ID)]

        assert frames == ["data: [DONE]\n\n"]


class TestMidStreamCancellation:
    async def test_flipping_the_flag_mid_stream_stops_the_graph_driver(self):
        """The real producer loop checks the flag before every event: a cancel
        landing while the graph is still emitting must abandon the run early,
        mark it cancelled, and record the interruption exactly once."""
        fake = _FakeStreamsRedis()
        graph = _FakeGraph(total_events=30)
        config = {"configurable": {"stream_id": STREAM_ID}}
        received: list[str] = []
        two_chunks_seen = asyncio.Event()

        async def consume() -> None:
            async for frame in execute_graph_streaming(graph, {}, config):
                received.append(frame)
                if len([f for f in received if f.startswith("data: ")]) >= 2:
                    two_chunks_seen.set()

        record_interruption = AsyncMock()
        with (
            patch.object(redis_cache, "redis", fake),
            patch("app.helpers.agent_helpers.record_interruption", record_interruption),
        ):
            task = asyncio.create_task(consume())
            await two_chunks_seen.wait()
            await stream_manager.cancel_stream(STREAM_ID)
            await task

        data_frames = [f for f in received if f.startswith("data: ")]
        assert 2 <= len(data_frames) < 30
        assert graph.pulled < 30
        nostream = received[-2]
        assert json.loads(nostream.removeprefix("nostream: "))["cancelled"] is True
        assert received[-1] == "data: [DONE]\n\n"
        record_interruption.assert_awaited_once()
