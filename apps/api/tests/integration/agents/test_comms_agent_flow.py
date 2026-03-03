"""Integration tests for comms agent graph flow patterns.

Tests a simplified graph mimicking the comms agent pattern:
model node -> conditional routing -> tool node -> model node -> END.
Validates graph compilation, routing, tool execution, and checkpointing.
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tests.helpers import create_fake_llm_with_tool_calls
from tests.integration.conftest import SimpleState


@pytest.mark.integration
class TestCommsAgentFlow:
    """Test the comms agent graph execution pattern."""

    async def test_simple_graph_invoke(self, compiled_graph, thread_config):
        """Graph should process a human message and return an echo response."""
        result = await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=thread_config,
        )
        assert len(result["messages"]) == 2
        assert result["messages"][-1].content == "Echo: Hello"

    async def test_graph_with_tool_routing(self, agent_graph_with_tools, thread_config):
        """Graph should route to tool node when model returns tool calls."""
        result = await agent_graph_with_tools.ainvoke(
            {"messages": [HumanMessage(content="Greet someone")]},
            config=thread_config,
        )
        messages = result["messages"]

        # Expect: HumanMessage, AIMessage(tool_call), ToolMessage, AIMessage(final)
        assert len(messages) >= 3
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        assert len(tool_msgs) >= 1
        assert "Hello, World!" in tool_msgs[0].content

    async def test_tool_calls_are_executed(self, agent_graph_with_tools, thread_config):
        """Tool node should execute tool calls and produce ToolMessage results."""
        result = await agent_graph_with_tools.ainvoke(
            {"messages": [HumanMessage(content="Greet someone")]},
            config=thread_config,
        )
        tool_messages = [
            m for m in result["messages"] if isinstance(m, ToolMessage)
        ]
        assert len(tool_messages) > 0
        assert tool_messages[0].tool_call_id == "call_greet_001"

    async def test_checkpointing_persists_state(self, compiled_graph, thread_config):
        """Invoking the graph twice with the same thread should accumulate messages."""
        await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="First")]},
            config=thread_config,
        )
        state_after_first = await compiled_graph.aget_state(thread_config)
        first_msgs = state_after_first.values["messages"]
        assert len(first_msgs) == 2

        await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="Second")]},
            config=thread_config,
        )
        state_after_second = await compiled_graph.aget_state(thread_config)
        second_msgs = state_after_second.values["messages"]
        # Should have accumulated: 2 from first + 2 from second
        assert len(second_msgs) == 4
        assert second_msgs[-1].content == "Echo: Second"

    async def test_different_threads_are_isolated(self, compiled_graph):
        """Different thread IDs should have independent state."""
        config_a = {"configurable": {"thread_id": "thread-a"}}
        config_b = {"configurable": {"thread_id": "thread-b"}}

        await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="From A")]},
            config=config_a,
        )
        await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="From B")]},
            config=config_b,
        )

        state_a = await compiled_graph.aget_state(config_a)
        state_b = await compiled_graph.aget_state(config_b)

        assert state_a.values["messages"][-1].content == "Echo: From A"
        assert state_b.values["messages"][-1].content == "Echo: From B"

    async def test_graph_handles_empty_messages(self, compiled_graph, thread_config):
        """Graph should handle an empty message content gracefully."""
        result = await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content="")]},
            config=thread_config,
        )
        assert result["messages"][-1].content == "Echo: "
