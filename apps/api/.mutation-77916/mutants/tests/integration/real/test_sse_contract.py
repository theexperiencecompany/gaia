"""
Service tests: verify the exact SSE wire format yielded by subscribe_stream.

Calls real StreamManager.subscribe_stream() against real Redis Streams.
Asserts on the exact strings that reach the HTTP response body: replayable
frames are id-tagged (``id: <entry-id>\\ndata: {json}\\n\\n``) while control
frames ([DONE], errors, keepalives) carry no id line.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.core.stream_manager import StreamManager

# Redis Stream entry ids ("<ms>-<seq>") double as SSE event ids.
_SSE_ID_LINE = re.compile(r"^id: \d+-\d+\n")


def _strip_id(frame: str) -> str:
    """Assert a replayable frame carries an SSE id line and return the rest."""
    match = _SSE_ID_LINE.match(frame)
    assert match is not None, f"Missing SSE id line: {frame!r}"
    return frame[match.end() :]


@pytest.mark.service
class TestSSEContract:
    """Verify the SSE wire format contract of subscribe_stream."""

    async def test_text_chunks_are_id_tagged_sse_frames(self, real_redis):
        """Every text chunk yielded must match: id: <entry-id>\\ndata: {json}\\n\\n"""
        await StreamManager.start_stream("sse-1", "c1", "u1")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(0.1)
            await StreamManager.publish_chunk("sse-1", 'data: {"response": "Hello"}\n\n')
            await StreamManager.complete_stream("sse-1")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-1"):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        text_chunks = [c for c in received if '"response"' in c]
        assert len(text_chunks) == 1
        for chunk in text_chunks:
            data = _strip_id(chunk)
            assert data.startswith("data: "), f"Missing data: prefix: {chunk!r}"
            assert data.endswith("\n\n"), f"Missing \\n\\n terminator: {chunk!r}"
            json.loads(data[6:-2])

    async def test_cancel_yields_done_marker(self, real_redis):
        """On cancellation, subscriber must yield exactly 'data: [DONE]\\n\\n' (no id line)."""
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
        """On error, subscriber must yield: data: {"error": "..."}\\n\\n (no id line)."""
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
        assert error_chunks[0].startswith("data: ")
        assert error_chunks[0].endswith("\n\n")
        payload = json.loads(error_chunks[0][6:-2])
        assert payload["error"] == "LLM timed out"

    async def test_keepalive_format(self, real_redis):
        """Idle streams must yield keepalive as exactly: data: {"keepalive":true}\\n\\n"""
        await StreamManager.start_stream("sse-4", "c4", "u4")
        received: list[str] = []

        async def publisher():
            await asyncio.sleep(2.5)
            await StreamManager.complete_stream("sse-4")

        async def subscriber():
            async for chunk in StreamManager.subscribe_stream("sse-4", keepalive_interval=1):
                received.append(chunk)

        await asyncio.gather(publisher(), subscriber())

        keepalives = [c for c in received if "keepalive" in c]
        assert len(keepalives) >= 1
        assert keepalives[0] == 'data: {"keepalive":true}\n\n'

    async def test_full_stream_sequence(self, real_redis):
        """A complete stream: init chunk -> text -> tool_data, each replayed id-tagged."""
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

        # Every received frame must be replayable (id-tagged) and the stored
        # payloads must round-trip byte-identically, in order.
        assert [_strip_id(c) for c in received] == [init, text, tool]
