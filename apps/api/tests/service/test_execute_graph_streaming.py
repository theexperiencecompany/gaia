"""
Service tests: call real execute_graph_streaming() with a real compiled graph.

Only mock: LLM (FakeMessagesListChatModel).
Real: graph.astream(), event parsing, tool_call deduplication, nostream marker,
cancellation check (via real Redis).
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage

from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.core.stream_manager import StreamManager
from app.helpers.agent_helpers import execute_graph_streaming
from tests.helpers import create_fake_llm
from tests.integration.agents.test_comms_agent_flow import (
    _common_patches,
    _make_chroma_store_mock,
)


@pytest.mark.service
class TestExecuteGraphStreamingReal:
    """Call real execute_graph_streaming with a real compiled graph."""

    async def test_yields_nostream_completion_marker(self, real_redis):
        """Streaming must yield a nostream: chunk with the complete_message."""
        fake_llm = create_fake_llm(["The answer is 42."])
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                state = {"messages": [HumanMessage(content="What is the meaning?")]}
                config = {
                    "configurable": {
                        "thread_id": "stream-test-1",
                        "user_id": "stream-user-1",
                    },
                    # Required so execute_graph_streaming accumulates complete_message
                    "agent_name": "comms_agent",
                }

                chunks = []
                async for chunk in execute_graph_streaming(graph, state, config):
                    chunks.append(chunk)

        nostream_chunks = [c for c in chunks if c.startswith("nostream: ")]
        assert len(nostream_chunks) == 1, (
            f"Expected exactly 1 nostream marker, got {len(nostream_chunks)}"
        )
        payload = json.loads(nostream_chunks[0].replace("nostream: ", ""))
        assert "complete_message" in payload
        assert len(payload["complete_message"]) > 0

    async def test_yields_sse_data_chunks(self, real_redis):
        """Streaming must yield data: chunks with response text."""
        fake_llm = create_fake_llm(["Hello world."])
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                state = {"messages": [HumanMessage(content="Say hello")]}
                config = {
                    "configurable": {
                        "thread_id": "stream-test-2",
                        "user_id": "stream-user-2",
                    },
                    "agent_name": "comms_agent",
                }

                chunks = []
                async for chunk in execute_graph_streaming(graph, state, config):
                    chunks.append(chunk)

        data_chunks = [c for c in chunks if c.startswith("data: ")]
        assert len(data_chunks) > 0, "Must yield at least one data: chunk"

    async def test_cancellation_stops_streaming(self, real_redis):
        """When stream_id is cancelled, streaming must stop with nostream marker."""
        stream_id = "cancel-stream-test"
        await StreamManager.start_stream(stream_id, "conv-cancel", "user-cancel")
        await StreamManager.cancel_stream(stream_id)

        fake_llm = create_fake_llm(["This should be cut short."])
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                state = {"messages": [HumanMessage(content="Long task")]}
                config = {
                    "configurable": {
                        "thread_id": "cancel-stream-test",
                        "user_id": "user-cancel",
                        "stream_id": stream_id,
                    },
                    "agent_name": "comms_agent",
                }

                chunks = []
                async for chunk in execute_graph_streaming(graph, state, config):
                    chunks.append(chunk)

        nostream = [c for c in chunks if "nostream" in c]
        assert len(nostream) >= 1
