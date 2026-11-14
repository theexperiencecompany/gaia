"""Integration tests for StreamManager's stream bookkeeping against real Redis."""

from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.stream_manager import StreamManager
from app.db.redis import redis_cache


def _stream_id() -> str:
    return f"test-stream-{uuid4().hex[:12]}"


def _sse_chunk(content: str) -> str:
    return f"data: {json.dumps({'content': content})}\n\n"


@pytest.mark.integration
class TestStreamMetadata:
    async def test_complete_stream_marks_progress_complete(self, real_redis):
        """complete_stream sets is_complete=True in the progress record."""
        sid = _stream_id()
        await StreamManager.start_stream(sid, "conv-done", "user-done")

        await StreamManager.complete_stream(sid)

        progress = await StreamManager.get_progress(sid)
        assert progress is not None
        assert progress["is_complete"] is True


@pytest.mark.integration
class TestStreamRedisFailure:
    """Test behavior when Redis is unavailable."""

    async def test_publish_does_not_raise_when_redis_unavailable(self):
        """publish_chunk silently no-ops when redis is None."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            await StreamManager.publish_chunk(sid, _sse_chunk("orphan"))

    async def test_start_stream_gracefully_handles_redis_down(self):
        """start_stream does not crash when Redis set fails."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            await StreamManager.start_stream(sid, "conv-noredis", "user-noredis")

        with patch.object(redis_cache, "redis", None):
            progress = await StreamManager.get_progress(sid)
            assert progress is None

    async def test_cancel_stream_gracefully_handles_redis_down(self):
        """cancel_stream does not crash when Redis is unavailable."""
        sid = _stream_id()

        with patch.object(redis_cache, "redis", None):
            result = await StreamManager.cancel_stream(sid)
            assert result is True
