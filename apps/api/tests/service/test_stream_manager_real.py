"""
Service tests: call real StreamManager methods against real Redis.

The conftest patches redis_cache.redis to a real Redis connection.
StreamManager class methods run unmodified.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.stream_manager import StreamManager


@pytest.mark.service
class TestStreamManagerReal:
    """Call real StreamManager methods against real Redis."""

    async def test_start_and_get_progress(self, real_redis):
        """start_stream must create progress retrievable by get_progress."""
        await StreamManager.start_stream("s1", "conv-1", "user-1")

        progress = await StreamManager.get_progress("s1")
        assert progress is not None
        assert progress["conversation_id"] == "conv-1"
        assert progress["user_id"] == "user-1"
        assert progress["is_complete"] is False

    async def test_publish_and_subscribe(self, real_redis):
        """publish_chunk must deliver to subscribe_stream."""
        await StreamManager.start_stream("s2", "conv-2", "user-2")

        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("s2", 'data: {"response": "Hello"}\n\n')
            await StreamManager.publish_chunk("s2", 'data: {"response": " world"}\n\n')
            await StreamManager.complete_stream("s2")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("s2"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        text_chunks = [c for c in received if '"response"' in c]
        assert len(text_chunks) == 2
        assert any("Hello" in c for c in text_chunks)
        assert any("world" in c for c in text_chunks)

    async def test_complete_stream_terminates_subscriber(self, real_redis):
        """complete_stream sends DONE signal; subscriber must stop."""
        await StreamManager.start_stream("s3", "conv-3", "user-3")

        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("s3", 'data: {"response": "Hi"}\n\n')
            await StreamManager.complete_stream("s3")
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("s3", 'data: {"response": "Ghost"}\n\n')

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("s3"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        assert not any("Ghost" in c for c in received)

    async def test_cancel_terminates_subscriber_with_done(self, real_redis):
        """cancel_stream sends CANCELLED signal; subscriber yields data: [DONE]."""
        await StreamManager.start_stream("s4", "conv-4", "user-4")

        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("s4", 'data: {"response": "before"}\n\n')
            await StreamManager.cancel_stream("s4")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("s4"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        assert any("before" in c for c in received)
        assert any("[DONE]" in c for c in received)

    async def test_is_cancelled_flag(self, real_redis):
        """cancel_stream must make is_cancelled return True."""
        await StreamManager.start_stream("s5", "conv-5", "user-5")

        assert not await StreamManager.is_cancelled("s5")
        await StreamManager.cancel_stream("s5")
        assert await StreamManager.is_cancelled("s5")

    async def test_update_progress_accumulates_text(self, real_redis):
        """update_progress must append message_chunk to complete_message."""
        await StreamManager.start_stream("s6", "conv-6", "user-6")

        await StreamManager.update_progress("s6", message_chunk="Hello ")
        await StreamManager.update_progress("s6", message_chunk="world")

        progress = await StreamManager.get_progress("s6")
        assert progress["complete_message"] == "Hello world"

    async def test_update_progress_merges_tool_data(self, real_redis):
        """update_progress must merge tool_data arrays."""
        await StreamManager.start_stream("s7", "conv-7", "user-7")

        await StreamManager.update_progress(
            "s7",
            tool_data={"tool_data": [{"tool_name": "search", "data": {}}]},
        )
        await StreamManager.update_progress(
            "s7",
            tool_data={"tool_data": [{"tool_name": "calendar", "data": {}}]},
        )

        progress = await StreamManager.get_progress("s7")
        tool_names = [t["tool_name"] for t in progress["tool_data"]["tool_data"]]
        assert tool_names == ["search", "calendar"]

    async def test_cleanup_removes_all_keys(self, real_redis):
        """cleanup must delete progress and signal keys."""
        await StreamManager.start_stream("s8", "conv-8", "user-8")
        await StreamManager.cancel_stream("s8")

        assert await StreamManager.get_progress("s8") is not None

        await StreamManager.cleanup("s8")

        assert await StreamManager.get_progress("s8") is None
        assert not await StreamManager.is_cancelled("s8")

    async def test_set_error_terminates_subscriber_with_error_message(self, real_redis):
        """set_error stores error in progress and sends ERROR signal."""
        await StreamManager.start_stream("s9", "conv-9", "user-9")

        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.set_error("s9", "agent crashed")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("s9"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        error_chunks = [c for c in received if "error" in c]
        assert len(error_chunks) >= 1
        payload = json.loads(error_chunks[0][6:-2])
        assert "agent crashed" in payload["error"]
