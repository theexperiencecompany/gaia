"""
Integration tests for the Chat Streaming Pipeline (Redis SSE).

Tests the full StreamManager lifecycle using real Redis pub/sub:
start_stream, publish_chunk, subscribe_stream, cancel_stream,
progress tracking, concurrent isolation, and error handling.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.constants.cache import (
    STREAM_SIGNAL_PREFIX,
)
from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache


def _stream_id() -> str:
    return f"test-stream-{uuid4().hex[:12]}"


def _sse_chunk(content: str) -> str:
    return f"data: {json.dumps({'content': content})}\n\n"


@pytest.mark.integration
class TestChatStreamingPipeline:
    """Full streaming lifecycle: start -> publish -> subscribe -> verify."""

    async def test_full_streaming_lifecycle(self, real_redis):
        """Start a stream, publish chunks, subscribe, and verify all chunks arrive in order."""
        sid = _stream_id()
        conv_id = f"conv-{uuid4().hex[:8]}"
        user_id = "user-lifecycle"

        await StreamManager.start_stream(sid, conv_id, user_id)

        chunks_to_send = [_sse_chunk(f"token-{i}") for i in range(5)]

        async def publisher():
            await asyncio.sleep(0.05)
            for chunk in chunks_to_send:
                await StreamManager.publish_chunk(sid, chunk)
                await asyncio.sleep(0.01)
            await StreamManager.complete_stream(sid)

        received: list[str] = []

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                received.append(chunk)

        pub_task = asyncio.create_task(publisher())
        sub_task = asyncio.create_task(subscriber())

        await asyncio.wait_for(asyncio.gather(pub_task, sub_task), timeout=10)

        # Filter out keepalive heartbeats — they're transparent and not part of content
        content_chunks = [c for c in received if '{"keepalive":true}' not in c]
        assert content_chunks == chunks_to_send
        assert len(content_chunks) == 5

    async def test_stream_cancellation_mid_flight(self, real_redis):
        """Cancel a stream mid-flight; subscriber gets the cancellation signal."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-cancel", "user-cancel")

        async def publisher():
            await asyncio.sleep(0.05)
            await StreamManager.publish_chunk(sid, _sse_chunk("before-cancel"))
            await asyncio.sleep(0.05)
            await StreamManager.cancel_stream(sid)

        received: list[str] = []

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                received.append(chunk)

        pub_task = asyncio.create_task(publisher())
        sub_task = asyncio.create_task(subscriber())

        await asyncio.wait_for(asyncio.gather(pub_task, sub_task), timeout=10)

        # Filter out keepalive heartbeats before asserting
        non_keepalive = [c for c in received if '{"keepalive":true}' not in c]
        # Should receive the chunk before cancel, plus the [DONE] signal from cancellation
        assert non_keepalive[0] == _sse_chunk("before-cancel")
        assert non_keepalive[-1] == "data: [DONE]\n\n"

        # Verify cancellation flag was set in Redis
        is_cancelled = await StreamManager.is_cancelled(sid)
        assert is_cancelled is True

        # Verify progress reflects cancellation
        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["is_cancelled"] is True

    async def test_concurrent_streams_no_data_leakage(self, real_redis):
        """Two simultaneous streams for different users must not leak data."""
        sid_a = _stream_id()
        sid_b = _stream_id()

        await StreamManager.start_stream(sid_a, "conv-a", "user-a")
        await StreamManager.start_stream(sid_b, "conv-b", "user-b")

        chunks_a = [_sse_chunk(f"a-{i}") for i in range(3)]
        chunks_b = [_sse_chunk(f"b-{i}") for i in range(3)]

        async def publish_for(sid: str, chunks: list[str]):
            await asyncio.sleep(0.05)
            for chunk in chunks:
                await StreamManager.publish_chunk(sid, chunk)
                await asyncio.sleep(0.01)
            await StreamManager.complete_stream(sid)

        received_a: list[str] = []
        received_b: list[str] = []

        async def subscribe_for(sid: str, dest: list[str]):
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                dest.append(chunk)

        tasks = [
            asyncio.create_task(publish_for(sid_a, chunks_a)),
            asyncio.create_task(publish_for(sid_b, chunks_b)),
            asyncio.create_task(subscribe_for(sid_a, received_a)),
            asyncio.create_task(subscribe_for(sid_b, received_b)),
        ]

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)

        # Filter keepalives before checking content isolation
        content_a = [c for c in received_a if '{"keepalive":true}' not in c]
        content_b = [c for c in received_b if '{"keepalive":true}' not in c]
        assert content_a == chunks_a
        assert content_b == chunks_b
        # No cross-contamination
        for chunk in content_a:
            assert chunk not in content_b
        for chunk in content_b:
            assert chunk not in content_a

    async def test_chunk_ordering_rapid_publish(self, real_redis):
        """Rapidly published chunks must arrive in exact order."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-order", "user-order")

        num_chunks = 50
        chunks = [_sse_chunk(f"seq-{i:04d}") for i in range(num_chunks)]

        async def publisher():
            await asyncio.sleep(0.05)
            for chunk in chunks:
                await StreamManager.publish_chunk(sid, chunk)
            await StreamManager.complete_stream(sid)

        received: list[str] = []

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                received.append(chunk)

        pub_task = asyncio.create_task(publisher())
        sub_task = asyncio.create_task(subscriber())

        await asyncio.wait_for(asyncio.gather(pub_task, sub_task), timeout=15)

        # Filter keepalives — rapid publish may interleave with heartbeats
        content_chunks = [c for c in received if '{"keepalive":true}' not in c]
        assert content_chunks == chunks
        assert len(content_chunks) == num_chunks


@pytest.mark.integration
class TestStreamMetadata:
    """Verify stream metadata (progress) is correctly stored and retrievable."""

    async def test_start_stream_stores_metadata(self, real_redis):
        """start_stream creates a progress entry with correct conversation_id and user_id."""
        sid = _stream_id()
        conv_id = f"conv-{uuid4().hex[:8]}"
        user_id = "user-meta"

        await StreamManager.start_stream(sid, conv_id, user_id)

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["conversation_id"] == conv_id
        assert progress["user_id"] == user_id
        assert progress["is_complete"] is False
        assert progress["is_cancelled"] is False
        assert progress["complete_message"] == ""
        assert progress["error"] is None

    async def test_update_progress_appends_message(self, real_redis):
        """update_progress accumulates message chunks in complete_message."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-prog", "user-prog")

        await StreamManager.update_progress(sid, message_chunk="Hello ")
        await StreamManager.update_progress(sid, message_chunk="world!")

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["complete_message"] == "Hello world!"

    async def test_update_progress_merges_tool_data(self, real_redis):
        """update_progress merges tool_data dicts correctly."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-tool", "user-tool")

        await StreamManager.update_progress(sid, tool_data={"search_query": "test"})
        await StreamManager.update_progress(sid, tool_data={"result_count": 5})

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["tool_data"]["search_query"] == "test"
        assert progress["tool_data"]["result_count"] == 5

    async def test_complete_stream_marks_progress_complete(self, real_redis):
        """complete_stream sets is_complete=True in the progress record."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-done", "user-done")

        await StreamManager.complete_stream(sid)

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["is_complete"] is True

    async def test_set_error_records_error_message(self, real_redis):
        """set_error stores error in progress and publishes error signal."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-err", "user-err")

        received: list[str] = []

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                received.append(chunk)

        sub_task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.05)

        await StreamManager.set_error(sid, "LLM rate limit exceeded")

        await asyncio.wait_for(sub_task, timeout=10)

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["error"] == "LLM rate limit exceeded"

        # Subscriber should have received an error chunk (filter out keepalives)
        error_chunks = [c for c in received if '{"keepalive":true}' not in c]
        assert len(error_chunks) == 1
        error_data = json.loads(error_chunks[0].removeprefix("data: ").strip())
        assert "error" in error_data
        assert error_data["error"] == "LLM rate limit exceeded"

    async def test_cleanup_removes_redis_keys(self, real_redis):
        """cleanup deletes all Redis keys for the stream."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-clean", "user-clean")

        # Set a cancellation signal too so both keys exist
        await redis_cache.set(f"{STREAM_SIGNAL_PREFIX}{sid}", "cancelled")

        await StreamManager.cleanup(sid)

        progress = await StreamManager.get_progress(sid)
        assert progress is None

        signal = await redis_cache.get(f"{STREAM_SIGNAL_PREFIX}{sid}")
        assert signal is None


@pytest.mark.integration
class TestStreamRedisFailure:
    """Test behavior when Redis is unavailable."""

    async def test_subscribe_returns_immediately_when_redis_unavailable(self):
        """subscribe_stream yields nothing and returns when redis is None."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            received: list[str] = []
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=1
            ):
                received.append(chunk)

        assert received == []

    async def test_publish_does_not_raise_when_redis_unavailable(self):
        """publish_chunk silently no-ops when redis is None."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            # Should not raise
            await StreamManager.publish_chunk(sid, _sse_chunk("orphan"))

    async def test_start_stream_gracefully_handles_redis_down(self):
        """start_stream does not crash when Redis set fails."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            # redis_cache.set returns early when redis is None
            await StreamManager.start_stream(sid, "conv-noredis", "user-noredis")

        # No progress stored since Redis was down
        with patch.object(redis_cache, "redis", None):
            progress = await StreamManager.get_progress(sid)
            assert progress is None

    async def test_cancel_stream_gracefully_handles_redis_down(self):
        """cancel_stream does not crash when Redis is unavailable."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            result = await StreamManager.cancel_stream(sid)
            # Still returns True (the method always returns True)
            assert result is True


@pytest.mark.integration
class TestStreamKeepalive:
    """Test keepalive behavior during idle periods."""

    async def test_keepalive_sent_during_idle(self, real_redis):
        """Subscriber receives keepalive when no data arrives within interval."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-ka", "user-ka")

        received: list[str] = []

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=0.3
            ):
                received.append(chunk)
                # After receiving first keepalive, stop
                if '{"keepalive":true}' in chunk:
                    break

        async def delayed_complete():
            # Wait longer than the keepalive interval, then complete
            await asyncio.sleep(0.6)
            await StreamManager.complete_stream(sid)

        sub_task = asyncio.create_task(subscriber())
        complete_task = asyncio.create_task(delayed_complete())

        await asyncio.wait_for(sub_task, timeout=5)
        complete_task.cancel()

        # Should have received at least one keepalive
        keepalives = [c for c in received if '{"keepalive":true}' in c]
        assert len(keepalives) >= 1
        assert keepalives[0] == 'data: {"keepalive":true}\n\n'


@pytest.mark.integration
class TestMultipleSubscribers:
    """Test multiple subscribers to the same stream channel."""

    async def test_multiple_subscribers_receive_same_chunks(self, real_redis):
        """Two subscribers to the same stream both receive all chunks."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-multi", "user-multi")

        chunks = [_sse_chunk(f"multi-{i}") for i in range(3)]

        async def publisher():
            await asyncio.sleep(0.1)
            for chunk in chunks:
                await StreamManager.publish_chunk(sid, chunk)
                await asyncio.sleep(0.01)
            await StreamManager.complete_stream(sid)

        received_1: list[str] = []
        received_2: list[str] = []

        async def subscriber(dest: list[str]):
            async for chunk in StreamManager.subscribe_stream(
                sid, keepalive_interval=5
            ):
                dest.append(chunk)

        tasks = [
            asyncio.create_task(publisher()),
            asyncio.create_task(subscriber(received_1)),
            asyncio.create_task(subscriber(received_2)),
        ]

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)

        # Filter keepalives before comparing content
        content_1 = [c for c in received_1 if '{"keepalive":true}' not in c]
        content_2 = [c for c in received_2 if '{"keepalive":true}' not in c]
        assert content_1 == chunks
        assert content_2 == chunks
