"""Integration tests for graph conditional routing.

Tests that conditional edges correctly route between nodes and that
state accumulates properly across multiple node invocations.
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from tests.integration.conftest import SimpleState


def _build_routing_graph(memory_saver: MemorySaver):
    """Build a graph with conditional routing based on message content.

    Route logic:
    - If the last message contains "urgent" -> route to "urgent_handler"
    - Otherwise -> route to "normal_handler"
    Both handlers set the `route` field so tests can verify the path taken.
    """

    def classifier(state: SimpleState) -> dict[str, Any]:
        last = state.messages[-1] if state.messages else None
        content = last.content.lower() if last else ""
        route = "urgent" if "urgent" in content else "normal"
        return {"route": route}

    def route_decision(state: SimpleState) -> str:
        return "urgent_handler" if state.route == "urgent" else "normal_handler"

    def urgent_handler(state: SimpleState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content="URGENT: Handling immediately")],
        }

    def normal_handler(state: SimpleState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content="Normal: Processing request")],
        }

    builder = StateGraph(SimpleState)
    builder.add_node("classifier", classifier)
    builder.add_node("urgent_handler", urgent_handler)
    builder.add_node("normal_handler", normal_handler)

    builder.set_entry_point("classifier")
    builder.add_conditional_edges(
        "classifier",
        route_decision,
        {"urgent_handler": "urgent_handler", "normal_handler": "normal_handler"},
    )
    builder.add_edge("urgent_handler", END)
    builder.add_edge("normal_handler", END)

    return builder.compile(checkpointer=memory_saver)


@pytest.mark.integration
class TestGraphRouting:
    """Test conditional routing in a compiled graph."""

    async def test_routes_to_normal_handler(self, memory_saver, thread_config):
        """Non-urgent messages should route through the normal handler."""
        graph = _build_routing_graph(memory_saver)
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="How is the weather?")]},
            config=thread_config,
        )
        assert result["route"] == "normal"
        assert result["messages"][-1].content == "Normal: Processing request"

    async def test_routes_to_urgent_handler(self, memory_saver, thread_config):
        """Messages containing 'urgent' should route through the urgent handler."""
        graph = _build_routing_graph(memory_saver)
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="This is urgent!")]},
            config=thread_config,
        )
        assert result["route"] == "urgent"
        assert result["messages"][-1].content == "URGENT: Handling immediately"

    async def test_both_paths_reachable(self, memory_saver):
        """Both routing paths should be reachable with appropriate inputs."""
        graph = _build_routing_graph(memory_saver)

        normal_result = await graph.ainvoke(
            {"messages": [HumanMessage(content="normal question")]},
            config={"configurable": {"thread_id": "routing-normal"}},
        )
        urgent_result = await graph.ainvoke(
            {"messages": [HumanMessage(content="urgent matter")]},
            config={"configurable": {"thread_id": "routing-urgent"}},
        )

        assert normal_result["route"] == "normal"
        assert urgent_result["route"] == "urgent"

    async def test_state_accumulates_across_nodes(self, memory_saver, thread_config):
        """State fields set in one node should be visible after the graph finishes."""
        graph = _build_routing_graph(memory_saver)
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hello")]},
            config=thread_config,
        )
        # classifier sets route, normal_handler adds a message
        assert result["route"] == "normal"
        assert len(result["messages"]) == 2  # HumanMessage + AIMessage

    async def test_checkpoint_captures_route(self, memory_saver, thread_config):
        """Checkpointed state should include the route field set during execution."""
        graph = _build_routing_graph(memory_saver)
        await graph.ainvoke(
            {"messages": [HumanMessage(content="urgent fix needed")]},
            config=thread_config,
        )
        state = await graph.aget_state(thread_config)
        assert state.values["route"] == "urgent"
