"""Integration tests for tool execution within the real production agent graph.

Tests that tools registered with create_agent are invoked correctly when the
fake LLM emits tool calls, and that results are properly wired back into the
graph state via the real DynamicToolNode.

DELETE app/override/langgraph_bigtool/create_agent.py → every test below fails.
DELETE app/override/langgraph_bigtool/utils.py → every test below fails.
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from app.override.langgraph_bigtool.create_agent import create_agent
from tests.helpers import (
    BindableToolsFakeModel,
    create_fake_llm,
    create_fake_llm_with_tool_calls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread_config() -> dict:
    return {"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}}


def _build_registry():
    @tool
    def add_numbers(a: int, b: int) -> str:
        """Add two numbers together and return the result as a string."""
        return str(a + b)

    return {"add_numbers": add_numbers}


def _compile(llm, end_graph_hooks=None):
    """Compile the real create_agent graph with the add_numbers tool registry."""
    builder = create_agent(
        llm=llm,
        tool_registry=_build_registry(),
        disable_retrieve_tools=True,
        initial_tool_ids=["add_numbers"],
        agent_name="tool_execution_test_agent",
        end_graph_hooks=end_graph_hooks,
    )
    return builder.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolExecution:
    """Tool execution verified through real create_agent graph invocation."""

    async def test_tool_call_produces_tool_message(self):
        """Fake LLM returning a tool call must produce a ToolMessage in state.

        Fails if DynamicToolNode is removed or should_continue stops routing
        AIMessages with tool_calls to the 'tools' node.
        """
        tool_call = {
            "name": "add_numbers",
            "args": {"a": 3, "b": 7},
            "id": "call_add_001",
            "type": "tool_call",
        }
        graph = _compile(
            create_fake_llm_with_tool_calls([tool_call, "The answer is 10."])
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Add 3 and 7")]},
            config=_thread_config(),
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "A tool call from the LLM must produce at least one ToolMessage. "
            "DynamicToolNode may not be executing tools correctly."
        )
        assert tool_messages[0].tool_call_id == "call_add_001", (
            f"ToolMessage.tool_call_id must match the AIMessage call ID. "
            f"Got: {tool_messages[0].tool_call_id!r}"
        )
        assert tool_messages[0].content == "10", (
            f"add_numbers(3, 7) must return '10'. Got: {tool_messages[0].content!r}"
        )

    async def test_full_tool_cycle_message_sequence(self):
        """Human → AI(tool_call) → ToolMessage → AI(final) completes in correct order.

        Validates the full routing cycle: agent → tools → agent → end.
        Fails if any node in the real create_agent graph is missing or miswired.
        """
        tool_call = {
            "name": "add_numbers",
            "args": {"a": 5, "b": 5},
            "id": "call_cycle_001",
            "type": "tool_call",
        }
        graph = _compile(
            create_fake_llm_with_tool_calls([tool_call, "Done, the sum is 10."])
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="What is 5 + 5?")]},
            config=_thread_config(),
        )

        messages = result["messages"]
        types = [type(m).__name__ for m in messages]

        assert any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for m in messages
        ), f"Missing AIMessage with tool_calls. Message types: {types}"

        assert any(isinstance(m, ToolMessage) for m in messages), (
            f"Missing ToolMessage after tool call. Message types: {types}"
        )

        final_ai = [
            m
            for m in messages
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
        ]
        assert len(final_ai) >= 1, (
            f"Missing final plain-text AIMessage after tool cycle. "
            f"Message types: {types}"
        )

    async def test_state_accumulates_across_turns(self):
        """Consecutive ainvoke calls on the same thread must accumulate messages.

        Fails if InMemorySaver checkpointing is broken in create_agent, or if
        the State reducer drops messages between turns.
        """
        graph = _compile(
            BindableToolsFakeModel(
                responses=[
                    AIMessage(content="First response."),
                    AIMessage(content="Second response."),
                ]
            )
        )
        config = _thread_config()

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Turn one")]}, config=config
        )
        count_after_1 = len((await graph.aget_state(config)).values["messages"])

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Turn two")]}, config=config
        )
        count_after_2 = len((await graph.aget_state(config)).values["messages"])

        assert count_after_2 > count_after_1, (
            "Messages must accumulate across turns via InMemorySaver. "
            f"count_after_1={count_after_1}, count_after_2={count_after_2}"
        )

        final_state = await graph.aget_state(config)
        human_contents = [
            m.content
            for m in final_state.values["messages"]
            if isinstance(m, HumanMessage)
        ]
        assert "Turn one" in human_contents, (
            f"Turn one HumanMessage must survive into final state. Got: {human_contents}"
        )
        assert "Turn two" in human_contents, (
            f"Turn two HumanMessage must be present in final state. Got: {human_contents}"
        )

    async def test_no_tool_call_produces_only_ai_message(self):
        """Plain text LLM response must not route to the tool node.

        Fails if should_continue in the real create_agent incorrectly routes
        plain-text AIMessages to the DynamicToolNode.
        """
        graph = _compile(create_fake_llm(["I can help you with that."]))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=_thread_config(),
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, (
            "Plain text response must not route to DynamicToolNode. "
            f"Got unexpected ToolMessages: {tool_messages}"
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, (
            "At least one AIMessage must be present in the final state."
        )
        assert not getattr(ai_messages[-1], "tool_calls", None), (
            "The final AIMessage must not have tool_calls for a plain text response."
        )
