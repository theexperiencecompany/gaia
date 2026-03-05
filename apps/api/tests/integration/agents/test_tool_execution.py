"""Integration tests for tool execution within a LangGraph agent.

Tests that tools bound to an agent are invoked correctly when the
FakeMessagesListChatModel emits tool calls, and that results are
properly wired back into the graph state.
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tests.helpers import create_fake_llm_with_tool_calls
from tests.integration.conftest import SimpleState


@pytest.fixture
def add_tool():
    """A tool that adds two numbers."""

    @tool
    def add_numbers(a: int, b: int) -> str:
        """Add two numbers together."""
        return str(a + b)

    return add_numbers


@pytest.fixture
def multi_tool_llm():
    """Fake LLM that calls add_numbers, then returns a final response."""
    tool_call = {
        "name": "add_numbers",
        "args": {"a": 3, "b": 7},
        "id": "call_add_001",
        "type": "tool_call",
    }
    return create_fake_llm_with_tool_calls([tool_call, "The answer is 10."])


@pytest.fixture
def tool_graph(add_tool, multi_tool_llm, memory_saver):
    """Build a graph with model and tool nodes for add_numbers."""

    def should_continue(state: SimpleState) -> str:
        last = state.messages[-1] if state.messages else None
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "end"

    def model_node(state: SimpleState) -> dict[str, Any]:
        response = multi_tool_llm.invoke(state.messages)
        return {"messages": [response]}

    tool_node = ToolNode([add_tool])

    builder = StateGraph(SimpleState)
    builder.add_node("model", model_node)
    builder.add_node("tools", tool_node)
    builder.set_entry_point("model")
    builder.add_conditional_edges(
        "model",
        should_continue,
        {"tools": "tools", "end": END},
    )
    builder.add_edge("tools", "model")

    return builder.compile(checkpointer=memory_saver)


@pytest.mark.integration
class TestToolExecution:
    """Test tool execution in a compiled agent graph."""

    async def test_tool_is_called_and_result_returned(self, tool_graph, thread_config):
        """The add_numbers tool should be called and produce a ToolMessage with result."""
        result = await tool_graph.ainvoke(
            {"messages": [HumanMessage(content="Add 3 and 7")]},
            config=thread_config,
        )
        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "10"
        assert tool_messages[0].tool_call_id == "call_add_001"

    async def test_final_response_follows_tool_result(self, tool_graph, thread_config):
        """After tool execution, the model should produce a final text response."""
        result = await tool_graph.ainvoke(
            {"messages": [HumanMessage(content="Add 3 and 7")]},
            config=thread_config,
        )
        final_msg = result["messages"][-1]
        assert isinstance(final_msg, AIMessage)
        assert "10" in final_msg.content

    async def test_tool_call_id_propagated(self, tool_graph, thread_config):
        """ToolMessage should carry the same tool_call_id as the AIMessage tool call."""
        result = await tool_graph.ainvoke(
            {"messages": [HumanMessage(content="compute")]},
            config=thread_config,
        )
        ai_messages = [
            m
            for m in result["messages"]
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        ]
        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(ai_messages) >= 1
        assert len(tool_messages) >= 1
        assert ai_messages[0].tool_calls[0]["id"] == tool_messages[0].tool_call_id

    async def test_multiple_invocations_with_checkpointing(
        self, tool_graph, thread_config
    ):
        """Subsequent invocations on the same thread should accumulate state."""
        await tool_graph.ainvoke(
            {"messages": [HumanMessage(content="First call")]},
            config=thread_config,
        )
        state = await tool_graph.aget_state(thread_config)
        msg_count_after_first = len(state.values["messages"])

        await tool_graph.ainvoke(
            {"messages": [HumanMessage(content="Second call")]},
            config=thread_config,
        )
        state = await tool_graph.aget_state(thread_config)
        msg_count_after_second = len(state.values["messages"])

        assert msg_count_after_second > msg_count_after_first
