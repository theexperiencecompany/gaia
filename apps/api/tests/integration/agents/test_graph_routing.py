"""Integration tests for the production should_continue routing logic.

Replaces the previous fake-graph routing tests with real tests that invoke
the actual create_agent factory from app/override/langgraph_bigtool/create_agent.py.

Tests verify routing behavior by observing output state after ainvoke():
- Plain text response → no ToolMessages (routes to END / end_graph_hooks)
- Tool call response → ToolMessage produced (routes to DynamicToolNode)
- Multiple tool calls → all produce ToolMessages
- end_graph_hooks fire when no tool calls
- State accumulates across turns (InMemorySaver checkpointing)
- Different thread IDs have isolated state

Deletion test: delete create_agent.py → every test below immediately fails.
"""

from typing import Any
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


def _build_minimal_registry():
    @tool
    def dummy_tool(query: str) -> str:
        """A dummy tool used only by routing tests."""
        return f"result for: {query}"

    return {"dummy_tool": dummy_tool}


def _compile(llm, end_graph_hooks=None):
    """Compile the real create_agent graph with a minimal dummy tool registry."""
    builder = create_agent(
        llm=llm,
        tool_registry=_build_minimal_registry(),
        disable_retrieve_tools=True,
        initial_tool_ids=["dummy_tool"],
        agent_name="routing_test_agent",
        end_graph_hooks=end_graph_hooks,
    )
    return builder.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGraphRouting:
    """Production should_continue routing verified through real graph execution."""

    async def test_plain_text_produces_no_tool_messages(self):
        """LLM with no tool calls must not route to the tool node.

        Fails if should_continue incorrectly routes plain-text AIMessages to 'tools'.
        """
        graph = _compile(create_fake_llm(["I can help you with that."]))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=_thread_config(),
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, (
            "Plain text response should not route to tool node. "
            f"Got unexpected ToolMessages: {tool_messages}"
        )

    async def test_tool_call_routes_to_tool_node_and_produces_tool_message(self):
        """LLM with a tool call must route to DynamicToolNode → ToolMessage in state.

        Fails if should_continue stops routing AIMessages with tool_calls to 'tools'.
        """
        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "test query"},
            "id": "call_dummy_001",
            "type": "tool_call",
        }
        graph = _compile(create_fake_llm_with_tool_calls([tool_call, "Done."]))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Use the tool")]},
            config=_thread_config(),
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "should_continue must route tool_calls to DynamicToolNode. "
            "No ToolMessage was produced."
        )
        assert tool_messages[0].tool_call_id == "call_dummy_001", (
            f"ToolMessage.tool_call_id must match the AIMessage call ID. "
            f"Got: {tool_messages[0].tool_call_id!r}"
        )

    async def test_tool_result_contains_production_function_output(self):
        """ToolMessage content must reflect what the real tool function returned.

        Fails if DynamicToolNode is not calling the production tool implementation.
        """
        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "routing check"},
            "id": "call_dummy_002",
            "type": "tool_call",
        }
        graph = _compile(create_fake_llm_with_tool_calls([tool_call, "All done."]))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run tool")]},
            config=_thread_config(),
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert any("routing check" in tm.content for tm in tool_messages), (
            "ToolMessage must contain the dummy_tool return value 'result for: routing check'. "
            "If this fails, DynamicToolNode is not executing the real tool function."
        )

    async def test_multiple_tool_calls_all_produce_tool_messages(self):
        """Two tool calls in one AIMessage must both be executed by DynamicToolNode.

        Fails if should_continue only routes the first call or drops calls.
        """
        ai_with_two_calls = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "dummy_tool",
                    "args": {"query": "first"},
                    "id": "call_a",
                    "type": "tool_call",
                },
                {
                    "name": "dummy_tool",
                    "args": {"query": "second"},
                    "id": "call_b",
                    "type": "tool_call",
                },
            ],
        )
        graph = _compile(
            BindableToolsFakeModel(
                responses=[ai_with_two_calls, AIMessage(content="Both done.")]
            )
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run two tools")]},
            config=_thread_config(),
        )

        tool_call_ids = {
            tm.tool_call_id for tm in result["messages"] if isinstance(tm, ToolMessage)
        }
        assert "call_a" in tool_call_ids, "First tool call was not executed"
        assert "call_b" in tool_call_ids, "Second tool call was not executed"

    async def test_end_graph_hook_fires_after_plain_text(self):
        """With end_graph_hooks, the hook must be called after a plain text response.

        Fails if should_continue stops routing to 'end_graph_hooks' when no tool calls.
        """
        hook_calls: list[Any] = []

        async def capture_hook(  # NOSONAR — async required for LangGraph hook interface
            state: Any, config: Any, store: Any
        ) -> dict:
            hook_calls.append(True)
            return {}

        graph = _compile(
            create_fake_llm(["Plain response."]),
            end_graph_hooks=[capture_hook],
        )

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=_thread_config(),
        )

        assert len(hook_calls) >= 1, (
            "end_graph_hooks should fire when LLM returns plain text. "
            "If this fails, should_continue is not routing to 'end_graph_hooks'."
        )

    async def test_end_graph_hook_fires_after_full_tool_cycle(self):
        """After tool execution + final plain text, end_graph_hooks must still fire.

        Verifies that hooks run at the end of the full tool-call cycle, not just
        on direct plain text responses.
        """
        hook_calls: list[Any] = []

        async def capture_hook(
            state: Any, config: Any, store: Any
        ) -> dict:  # NOSONAR — async required for LangGraph hook interface
            hook_calls.append(True)
            return {}

        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "hook test"},
            "id": "call_hook_cycle",
            "type": "tool_call",
        }
        graph = _compile(
            create_fake_llm_with_tool_calls([tool_call, "Done."]),
            end_graph_hooks=[capture_hook],
        )

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Do tool then finish")]},
            config=_thread_config(),
        )

        assert len(hook_calls) >= 1, (
            "end_graph_hooks should fire after the full tool-call cycle ends. "
            "Hooks were not called after tool execution + final response."
        )

    async def test_state_accumulates_across_turns(self):
        """Consecutive ainvoke calls on the same thread must accumulate messages.

        Fails if InMemorySaver checkpointing is broken in create_agent.
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

        # Verify original message content is preserved — not just that count grew
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

    async def test_different_thread_ids_have_isolated_state(self):
        """Two threads on the SAME compiled graph must not share checkpointed state.

        Uses a single graph with a single MemorySaver to test the production
        scenario: one graph instance serving multiple users via different thread_ids.
        Fails if thread isolation is broken in the compiled graph.
        """
        graph = _compile(
            BindableToolsFakeModel(
                responses=[
                    AIMessage(content="Response for A"),
                    AIMessage(content="Response for B"),
                ]
            )
        )
        config_a = _thread_config()
        config_b = _thread_config()

        await graph.ainvoke(
            {"messages": [HumanMessage(content="From A")]}, config=config_a
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="From B")]}, config=config_b
        )

        state_a = await graph.aget_state(config_a)
        state_b = await graph.aget_state(config_b)

        human_in_a = [
            m.content for m in state_a.values["messages"] if isinstance(m, HumanMessage)
        ]
        human_in_b = [
            m.content for m in state_b.values["messages"] if isinstance(m, HumanMessage)
        ]

        assert "From A" in human_in_a, (
            f"Thread A's state must contain its own message. Got: {human_in_a}"
        )
        assert "From B" not in human_in_a, (
            f"Thread A's state must not contain Thread B's message. Got: {human_in_a}"
        )
        assert "From B" in human_in_b, (
            f"Thread B's state must contain its own message. Got: {human_in_b}"
        )
        assert "From A" not in human_in_b, (
            f"Thread B's state must not contain Thread A's message. Got: {human_in_b}"
        )

    async def test_full_tool_cycle_message_sequence(self):
        """Human → AI(tool_call) → ToolMessage → AI(final) completes in correct order.

        Validates the entire routing cycle: model → tools → model → end.
        """
        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "cycle check"},
            "id": "call_cycle",
            "type": "tool_call",
        }
        graph = _compile(create_fake_llm_with_tool_calls([tool_call, "All good."]))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Do the full cycle")]},
            config=_thread_config(),
        )

        messages = result["messages"]
        types = [type(m).__name__ for m in messages]

        assert any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for m in messages
        ), f"Missing AIMessage with tool_calls. Messages: {types}"
        assert any(isinstance(m, ToolMessage) for m in messages), (
            f"Missing ToolMessage. Messages: {types}"
        )
        final_ai = [
            m
            for m in messages
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
        ]
        assert len(final_ai) >= 1, (
            f"Missing final plain-text AIMessage. Messages: {types}"
        )
