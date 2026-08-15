"""
Service tests: call real execute_graph_streaming() with a real compiled graph.

Only mock: LLM (FakeMessagesListChatModel).
Real: graph.astream(), event parsing, tool_call deduplication, nostream marker,
cancellation check (via real Redis).
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.core.stream_manager import StreamManager
from app.helpers.agent_helpers import execute_graph_streaming
from tests.helpers import create_fake_llm
from tests.integration.agents.test_comms_agent_flow import (
    _common_patches,
    _make_chroma_store_mock,
)


async def _collect_chunks(
    *,
    prompt: str,
    response: str,
    thread_id: str,
    user_id: str,
    stream_id: str | None = None,
) -> list[str]:
    fake_llm = create_fake_llm([response])
    store_mock = _make_chroma_store_mock()

    configurable: dict[str, str] = {"thread_id": thread_id, "user_id": user_id}
    if stream_id is not None:
        configurable["stream_id"] = stream_id

    patches = _common_patches(store_mock)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
            state = {"messages": [HumanMessage(content=prompt)]}
            config = {
                "configurable": configurable,
                # Required so execute_graph_streaming accumulates complete_message
                "agent_name": "comms_agent",
            }
            return [chunk async for chunk in execute_graph_streaming(graph, state, config)]


def _nostream_payload(chunks: list[str]) -> dict:
    markers = [c for c in chunks if c.startswith("nostream: ")]
    assert len(markers) == 1, f"Expected exactly 1 nostream marker, got {len(markers)}"
    return json.loads(markers[0].removeprefix("nostream: "))


@pytest.mark.service
class TestExecuteGraphStreamingReal:
    """Call real execute_graph_streaming with a real compiled graph."""

    async def test_yields_nostream_completion_marker(self, real_redis):
        """Streaming must yield a nostream: chunk with the complete_message."""
        chunks = await _collect_chunks(
            prompt="What is the meaning?",
            response="The answer is 42.",
            thread_id="stream-test-1",
            user_id="stream-user-1",
        )

        payload = _nostream_payload(chunks)
        assert "complete_message" in payload
        assert len(payload["complete_message"]) > 0

    async def test_yields_sse_data_chunks(self, real_redis):
        """Streaming must yield data: chunks with response text."""
        chunks = await _collect_chunks(
            prompt="Say hello",
            response="Hello world.",
            thread_id="stream-test-2",
            user_id="stream-user-2",
        )

        data_chunks = [c for c in chunks if c.startswith("data: ")]
        assert len(data_chunks) > 0, "Must yield at least one data: chunk"

    async def test_cancellation_stops_streaming(self, real_redis):
        """A cancelled stream must break out early and flag the marker as cancelled.

        Both runs are identical except for the Redis cancel flag, so the control
        run pins down what "not cancelled" looks like — without it, a stream that
        ran to completion would satisfy the cancelled-run assertions too.
        """
        control_id = "cancel-stream-control"
        cancelled_id = "cancel-stream-cancelled"
        for sid in (control_id, cancelled_id):
            await StreamManager.start_stream(sid, "conv-cancel", "user-cancel")
        await StreamManager.cancel_stream(cancelled_id)

        control_chunks = await _collect_chunks(
            prompt="Long task",
            response="This should run to completion.",
            thread_id=control_id,
            user_id="user-cancel",
            stream_id=control_id,
        )
        cancelled_chunks = await _collect_chunks(
            prompt="Long task",
            response="This should be cut short.",
            thread_id=cancelled_id,
            user_id="user-cancel",
            stream_id=cancelled_id,
        )

        assert _nostream_payload(cancelled_chunks)["cancelled"] is True
        assert "cancelled" not in _nostream_payload(control_chunks)
        assert len(cancelled_chunks) < len(control_chunks), (
            "Cancelled run must stop early, not emit the full stream: "
            f"{len(cancelled_chunks)} chunks vs {len(control_chunks)} uncancelled"
        )
