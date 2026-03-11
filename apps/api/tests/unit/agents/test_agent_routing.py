"""
Tests for the agent routing logic (should_continue) in create_agent.

The should_continue function is a closure inside create_agent. These tests
verify routing behavior by calling create_agent with a minimal LLM/tool setup
and inspecting what happens when the compiled graph is invoked with states
that have or don't have tool_calls on the last AIMessage.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.override.langgraph_bigtool.create_agent import create_agent
from tests.helpers import BindableToolsFakeModel


def _build_minimal_registry():
    @tool
    def dummy_tool(query: str) -> str:
        """A dummy tool for testing."""
        return f"result: {query}"

    return {"dummy_tool": dummy_tool}


def _make_mock_llm(response: AIMessage) -> BindableToolsFakeModel:
    """Create a fake LLM that always returns the given AIMessage."""
    return BindableToolsFakeModel(responses=[response])


def _extract_should_continue(builder):
    """
    Extract the should_continue function from the compiled graph builder.
    StateGraph stores conditional edges in _graph._edges or similar structures.
    We test indirectly by verifying the compiled graph's branching logic.
    """
    # Access the compiled branches from the StateGraph
    # In LangGraph, conditional edges are stored in the builder's branches dict
    branches = builder.branches
    return branches.get("agent")


def _get_agent_branch_ends(builder) -> dict:
    """
    Extract the 'ends' dict from the agent node's BranchSpec in a StateGraph builder.

    builder.branches["agent"] is a dict keyed by branch condition name.
    Each value is a BranchSpec NamedTuple with field `ends: dict[Hashable, str] | None`.
    We merge all ends dicts from all branches on 'agent' into one mapping.
    """
    agent_branches = builder.branches.get("agent", {})
    merged: dict = {}
    for branch_spec in agent_branches.values():
        if branch_spec.ends:
            merged.update(branch_spec.ends)
    return merged


@pytest.mark.unit
class TestShouldContinueLogicViaCreateAgent:
    """
    Tests for the routing logic in create_agent's should_continue closure.

    We verify routing by inspecting the compiled StateGraph's conditional edge
    path_map (stored in builder.branches["agent"].<BranchSpec>.ends).
    """

    @pytest.mark.asyncio
    async def test_agent_conditional_edge_is_registered(self):
        """The 'agent' node must have conditional edges registered in create_agent."""
        mock_llm = _make_mock_llm(AIMessage(content="done"))
        tool_registry = _build_minimal_registry()

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
        )

        agent_branches = builder.branches.get("agent")
        assert agent_branches is not None, (
            "Expected 'agent' conditional edge to exist in StateGraph branches. "
            "If this fails, the routing structure in create_agent has changed."
        )
        assert len(agent_branches) > 0, (
            "Expected at least one branch condition on 'agent' node."
        )

    @pytest.mark.asyncio
    async def test_no_tool_calls_no_end_graph_hooks_path_map_lacks_end_graph_hooks(
        self,
    ):
        """When no end_graph_hooks, 'end_graph_hooks' must not appear in path_map."""
        mock_llm = _make_mock_llm(AIMessage(content="Here is your answer."))
        tool_registry = _build_minimal_registry()

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
            end_graph_hooks=None,
        )

        ends = _get_agent_branch_ends(builder)
        assert "end_graph_hooks" not in ends.values(), (
            "When no end_graph_hooks are provided, routing should not include "
            "'end_graph_hooks' in the path map. This will fail if create_agent "
            "incorrectly registers the end_graph_hooks node."
        )

    @pytest.mark.asyncio
    async def test_end_graph_hooks_present_appear_in_path_map(self):
        """When end_graph_hooks are provided, 'end_graph_hooks' must appear in path_map."""
        mock_llm = _make_mock_llm(AIMessage(content="Done."))
        tool_registry = _build_minimal_registry()

        async def mock_hook(state, config, store):
            return state

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
            end_graph_hooks=[mock_hook],
        )

        ends = _get_agent_branch_ends(builder)
        assert "end_graph_hooks" in ends.values(), (
            "When end_graph_hooks are provided, 'end_graph_hooks' must appear in "
            "the agent's conditional edge path_map. If this fails, create_agent "
            "is no longer registering end_graph_hooks routing."
        )

    @pytest.mark.asyncio
    async def test_tools_node_always_in_path_map(self):
        """'tools' must always be reachable from the agent's routing path map."""
        mock_llm = _make_mock_llm(AIMessage(content="test"))
        tool_registry = _build_minimal_registry()

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
        )

        ends = _get_agent_branch_ends(builder)
        assert "tools" in ends.values(), (
            "'tools' must always be in the agent routing path map. "
            "If this fails, the create_agent routing logic has removed the tools route."
        )

    @pytest.mark.asyncio
    async def test_select_tools_in_path_map_when_retrieve_tools_enabled(self):
        """When retrieve_tools is enabled, 'select_tools' must be in the path map."""
        mock_llm = _make_mock_llm(AIMessage(content="test"))
        tool_registry = _build_minimal_registry()

        async def mock_retrieve(query: str, store=None, user_id=None) -> list:
            """Retrieve tools matching the query."""
            return []

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            retrieve_tools_coroutine=mock_retrieve,
            agent_name="test_agent",
        )

        ends = _get_agent_branch_ends(builder)
        assert "select_tools" in ends.values(), (
            "'select_tools' must be in path_map when retrieve_tools is enabled. "
            "If this fails, the conditional routing no longer supports tool retrieval."
        )

    @pytest.mark.asyncio
    async def test_select_tools_absent_when_retrieve_tools_disabled(self):
        """When disable_retrieve_tools=True, 'select_tools' must NOT be in path_map."""
        mock_llm = _make_mock_llm(AIMessage(content="test"))
        tool_registry = _build_minimal_registry()

        builder = create_agent(
            llm=mock_llm,
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
        )

        ends = _get_agent_branch_ends(builder)
        assert "select_tools" not in ends.values(), (
            "When disable_retrieve_tools=True, 'select_tools' must not appear in "
            "path_map. If this fails, the tool-retrieval routing is incorrectly "
            "registered even when disabled."
        )


@pytest.mark.unit
class TestShouldContinueBehavior:
    """
    Tests for the should_continue routing behavior via real compiled graph execution.

    NOTE: The full behavioral test suite for routing lives in
    tests/integration/agents/test_graph_routing.py (TestGraphRouting).
    Only the unique scenario not covered there is kept here.

    Unique test here:
    - LLM empty tool_calls list → treated as plain text (not in integration suite)
    """

    def _compile_graph(self, llm, end_graph_hooks=None):
        """Build and compile a minimal create_agent graph for routing behaviour tests."""
        builder = create_agent(
            llm=llm,
            tool_registry=_build_minimal_registry(),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="test_agent",
            end_graph_hooks=end_graph_hooks,
        )
        from langgraph.checkpoint.memory import MemorySaver

        return builder.compile(checkpointer=MemorySaver())

    @pytest.mark.asyncio
    async def test_empty_tool_calls_list_produces_no_tool_messages(self):
        """LLM returns AIMessage(tool_calls=[]) → treated as plain text → no ToolMessages.

        Fails if should_continue treats empty tool_calls as if there were tool calls.
        """
        graph = self._compile_graph(
            BindableToolsFakeModel(
                responses=[AIMessage(content="No tools needed.", tool_calls=[])]
            )
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config={"configurable": {"thread_id": "t4"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, (
            "Empty tool_calls list must not route to tool node."
        )

    @pytest.mark.asyncio
    async def test_tool_calls_route_to_tools_node(self):
        """LLM returns an AIMessage with tool_calls → routing goes to tools node → ToolMessage produced.

        Fails if should_continue stops routing AIMessages with non-empty tool_calls to 'tools'.
        """

        @tool
        def echo_tool(query: str) -> str:
            """Echo tool for routing test."""
            return f"echo: {query}"

        tool_call = {
            "name": "echo_tool",
            "args": {"query": "routing test"},
            "id": "call_route_001",
            "type": "tool_call",
        }
        llm = BindableToolsFakeModel(
            responses=[
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Done."),
            ]
        )
        builder = create_agent(
            llm=llm,
            tool_registry={"echo_tool": echo_tool},
            disable_retrieve_tools=True,
            initial_tool_ids=["echo_tool"],
            agent_name="test_agent",
        )
        from langgraph.checkpoint.memory import MemorySaver

        graph = builder.compile(checkpointer=MemorySaver())

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Use the tool")]},
            config={"configurable": {"thread_id": "t_tool_route"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "should_continue must route AIMessage with tool_calls to the tools node. "
            "No ToolMessage was produced — routing did not reach DynamicToolNode."
        )
        assert tool_messages[0].tool_call_id == "call_route_001", (
            f"ToolMessage.tool_call_id must match the AIMessage call ID 'call_route_001'. "
            f"Got: {tool_messages[0].tool_call_id!r}"
        )

    @pytest.mark.asyncio
    async def test_no_tool_calls_route_to_end(self):
        """LLM returns plain text (no tool_calls) → routing goes to END → only AIMessage in output.

        Fails if should_continue incorrectly routes plain-text AIMessages to the tools node.
        """
        plain_response = AIMessage(content="Here is the answer, no tools needed.")
        llm = BindableToolsFakeModel(responses=[plain_response])
        graph = self._compile_graph(llm)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Just answer")]},
            config={"configurable": {"thread_id": "t_plain_route"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, (
            "Plain text AIMessage must not route to the tools node. "
            f"Unexpected ToolMessages: {tool_messages}"
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, "Expected at least one AIMessage in output."
        final_ai = ai_messages[-1]
        assert final_ai.content == "Here is the answer, no tools needed.", (
            f"Final AIMessage content must match the fake LLM response. "
            f"Got: {final_ai.content!r}"
        )
