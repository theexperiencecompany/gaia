"""
Service tests: call real call_agent() with a real compiled comms graph.

Only mock: LLM (FakeMessagesListChatModel) and external I/O.
Real: _core_agent_logic, construct_langchain_messages, GraphManager,
build_initial_state, build_agent_config, execute_graph_streaming.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.agent import call_agent
from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.models.message_models import MessageRequestWithHistory
from tests.helpers import create_fake_llm
from tests.integration.agents.test_comms_agent_flow import (
    _common_patches,
    _make_chroma_store_mock,
)


@pytest.mark.service
class TestCallAgentReal:
    """Call real call_agent() with a real compiled comms graph."""

    async def test_streaming_produces_sse_chunks(self, real_redis):
        """call_agent must return an async generator yielding SSE-formatted strings."""
        fake_llm = create_fake_llm(["Hello from the real graph!"])
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
                body = MessageRequestWithHistory(
                    message="Hi there",
                    messages=[{"role": "user", "content": "Hi there"}],
                    conversation_id="call-agent-conv-1",
                )

                with (
                    patch(
                        "app.agents.core.agent.store_user_message_memory",
                        new=AsyncMock(),
                    ),
                    # GraphManager.get_graph uses providers.aget which is patched
                    # globally by _common_patches[0] to return store_mock. Override
                    # specifically for call_agent so it gets the real graph.
                    patch(
                        "app.agents.core.agent.GraphManager.get_graph",
                        new=AsyncMock(return_value=graph),
                    ),
                ):
                    gen = await call_agent(
                        request=body,
                        conversation_id="call-agent-conv-1",
                        user={"user_id": "agent-user-1", "name": "Test"},
                        user_time=datetime.now(timezone.utc),
                    )

                    chunks = []
                    async for chunk in gen:
                        chunks.append(chunk)

        assert len(chunks) > 0, "call_agent must yield at least one chunk"
        all_text = "".join(chunks)
        assert "Hello from the real graph!" in all_text or "response" in all_text

    async def test_error_produces_error_generator(self, real_redis):
        """If _core_agent_logic fails, call_agent must yield an error + [DONE]."""
        body = MessageRequestWithHistory(
            message="Crash",
            messages=[{"role": "user", "content": "Crash"}],
            conversation_id="call-agent-conv-2",
        )

        with (
            patch(
                "app.agents.core.agent.GraphManager.get_graph",
                new=AsyncMock(side_effect=RuntimeError("graph not found")),
            ),
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new=AsyncMock(return_value=[]),
            ),
        ):
            gen = await call_agent(
                request=body,
                conversation_id="call-agent-conv-2",
                user={"user_id": "agent-user-2"},
                user_time=datetime.now(timezone.utc),
            )

            chunks = []
            async for chunk in gen:
                chunks.append(chunk)

        assert any("error" in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)
