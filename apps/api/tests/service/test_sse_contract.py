"""
Service tests: verify the exact SSE wire format yielded by subscribe_stream.

Calls real StreamManager.subscribe_stream() against real Redis.
Asserts on the exact strings that reach the HTTP response body.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.stream_manager import StreamManager


@pytest.mark.service
class TestSSEContract:
    """Verify the SSE wire format contract of subscribe_stream."""

    async def test_text_chunks_have_data_prefix_and_double_newline(self, real_redis):
        """Every text chunk yielded must match: data: {json}\\n\\n"""
        await StreamManager.start_stream("sse-1", "c1", "u1")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk(
                "sse-1", 'data: {"response": "Hello"}\n\n'
            )
            await StreamManager.complete_stream("sse-1")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-1"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        text_chunks = [c for c in received if '"response"' in c]
        for chunk in text_chunks:
            assert chunk.startswith("data: "), f"Missing data: prefix: {chunk!r}"
            assert chunk.endswith("\n\n"), f"Missing \\n\\n terminator: {chunk!r}"
            json.loads(chunk[6:-2])

    async def test_cancel_yields_done_marker(self, real_redis):
        """On cancellation, subscriber must yield exactly 'data: [DONE]\\n\\n'."""
        await StreamManager.start_stream("sse-2", "c2", "u2")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.cancel_stream("sse-2")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-2"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        assert "data: [DONE]\n\n" in received

    async def test_error_yields_json_with_error_key(self, real_redis):
        """On error, subscriber must yield: data: {"error": "..."}\\n\\n"""
        await StreamManager.start_stream("sse-3", "c3", "u3")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.set_error("sse-3", "LLM timed out")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-3"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        error_chunks = [c for c in received if "error" in c]
        assert len(error_chunks) >= 1
        payload = json.loads(error_chunks[0][6:-2])
        assert payload["error"] == "LLM timed out"

    async def test_keepalive_format(self, real_redis):
        """Idle streams must yield keepalive as: data: {"keepalive":true}\\n\\n"""
        await StreamManager.start_stream("sse-4", "c4", "u4")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(2.5)
            await StreamManager.complete_stream("sse-4")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream(
                "sse-4", keepalive_interval=1
            ):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        keepalives = [c for c in received if "keepalive" in c]
        assert len(keepalives) >= 1
        payload = json.loads(keepalives[0][6:-2])
        assert payload["keepalive"] is True

    async def test_full_stream_sequence(self, real_redis):
        """A complete stream: init chunk -> text -> tool_data -> [DONE]."""
        await StreamManager.start_stream("sse-5", "c5", "u5")
        received: list[str] = []

        init = f"data: {json.dumps({'user_message_id': 'u1', 'bot_message_id': 'b1', 'stream_id': 'sse-5'})}\n\n"
        text = f"data: {json.dumps({'response': 'Answer'})}\n\n"
        tool = f"data: {json.dumps({'tool_data': {'tool_name': 'search', 'data': {}}})}\n\n"

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("sse-5", init)
            await StreamManager.publish_chunk("sse-5", text)
            await StreamManager.publish_chunk("sse-5", tool)
            await StreamManager.complete_stream("sse-5")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-5"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        # Filter keepalives: non-blocking get_message may yield a keepalive
        # before the publisher's 0.1s sleep completes.
        non_keepalive = [c for c in received if "keepalive" not in c]
        assert len(non_keepalive) == 3
        assert "user_message_id" in non_keepalive[0]
        assert "response" in non_keepalive[1]
        assert "tool_data" in non_keepalive[2]
