"""
Tests for the agent routing logic (should_continue) in create_agent.

The should_continue function is a closure inside create_agent. These tests
verify routing behavior by calling create_agent with a minimal LLM/tool setup
and inspecting what happens when the compiled graph is invoked with states
that have or don't have tool_calls on the last AIMessage.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.override.langgraph_bigtool.create_agent import create_agent


def _build_minimal_registry():
    @tool
    def dummy_tool(query: str) -> str:
        """A dummy tool for testing."""
        return f"result: {query}"

    return {"dummy_tool": dummy_tool}


def _make_mock_llm(response: AIMessage):
    """Create a mock LLM that always returns the given AIMessage."""
    mock_llm = MagicMock()
    mock_llm.with_config.return_value = mock_llm
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=response)
    mock_llm.invoke = MagicMock(return_value=response)
    return mock_llm


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

    Instead of copying the production closure (which gave false confidence), these
    tests invoke the actual create_agent compiled graph and assert on observable
    output state. If should_continue is changed or deleted, every test here breaks.

    Behaviors verified:
    - LLM plain text → no ToolMessages produced (routes to END / end_graph_hooks)
    - LLM tool call → ToolMessage produced with correct tool_call_id (routes to tools)
    - LLM multiple tool calls → all ToolMessages produced
    - LLM empty tool_calls list → no ToolMessages (treated as plain text)
    - end_graph_hooks fires on plain text response
    - end_graph_hooks fires after full tool-call cycle
    - Regular tool calls route to 'tools' (DynamicToolNode), not 'select_tools'
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
    async def test_plain_text_produces_no_tool_messages(self):
        """LLM plain text → should_continue routes to END, no ToolMessages in state.

        Fails if should_continue incorrectly routes plain AIMessages to 'tools'.
        """
        from tests.helpers import create_fake_llm

        graph = self._compile_graph(create_fake_llm(["I am done."]))
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config={"configurable": {"thread_id": "t1"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, (
            "Plain text response must not produce ToolMessages. "
            "should_continue is incorrectly routing to 'tools'."
        )

    @pytest.mark.asyncio
    async def test_tool_call_produces_tool_message_with_correct_id(self):
        """LLM tool call → should_continue routes to DynamicToolNode → ToolMessage.

        Fails if should_continue stops routing AIMessages with tool_calls to 'tools'.
        """
        from tests.helpers import create_fake_llm_with_tool_calls

        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "routing test"},
            "id": "tc_routing_001",
            "type": "tool_call",
        }
        graph = self._compile_graph(
            create_fake_llm_with_tool_calls([tool_call, "Done."])
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Use the tool")]},
            config={"configurable": {"thread_id": "t2"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "should_continue must route tool_calls to DynamicToolNode. "
            "No ToolMessage was produced."
        )
        assert tool_messages[0].tool_call_id == "tc_routing_001", (
            f"ToolMessage.tool_call_id must match the AIMessage call id. "
            f"Got: {tool_messages[0].tool_call_id!r}"
        )

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_all_produce_tool_messages(self):
        """LLM emits two tool calls → both execute → two ToolMessages in state.

        Fails if should_continue only routes one call or drops calls entirely.
        """
        ai_with_two_calls = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "dummy_tool",
                    "args": {"query": "first"},
                    "id": "tc_a",
                    "type": "tool_call",
                },
                {
                    "name": "dummy_tool",
                    "args": {"query": "second"},
                    "id": "tc_b",
                    "type": "tool_call",
                },
            ],
        )
        from tests.helpers import BindableToolsFakeModel

        graph = self._compile_graph(
            BindableToolsFakeModel(
                responses=[ai_with_two_calls, AIMessage(content="Both done.")]
            )
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run two tools")]},
            config={"configurable": {"thread_id": "t3"}},
        )

        ids = {
            tm.tool_call_id for tm in result["messages"] if isinstance(tm, ToolMessage)
        }
        assert "tc_a" in ids, "First tool call was not executed"
        assert "tc_b" in ids, "Second tool call was not executed"

    @pytest.mark.asyncio
    async def test_empty_tool_calls_list_produces_no_tool_messages(self):
        """LLM returns AIMessage(tool_calls=[]) → treated as plain text → no ToolMessages.

        Fails if should_continue treats empty tool_calls as if there were tool calls.
        """
        from tests.helpers import BindableToolsFakeModel

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
    async def test_end_graph_hook_fires_on_plain_text_response(self):
        """end_graph_hooks must be called when should_continue routes to 'end_graph_hooks'.

        Fails if should_continue stops routing plain text responses to 'end_graph_hooks'
        when hooks are registered.
        """
        from tests.helpers import create_fake_llm

        hook_calls: list[bool] = []

        async def capture_hook(state: object, config: object, store: object) -> dict:
            hook_calls.append(True)
            return {}

        graph = self._compile_graph(
            create_fake_llm(["Plain response."]),
            end_graph_hooks=[capture_hook],
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config={"configurable": {"thread_id": "t5"}},
        )

        assert len(hook_calls) >= 1, (
            "end_graph_hook must fire when LLM returns plain text. "
            "should_continue is not routing to 'end_graph_hooks'."
        )

    @pytest.mark.asyncio
    async def test_end_graph_hook_fires_after_full_tool_cycle(self):
        """After tool call + final plain text, end_graph_hooks must still fire.

        Verifies the hook runs after the full agent→tools→agent cycle completes.
        """
        from tests.helpers import create_fake_llm_with_tool_calls

        hook_calls: list[bool] = []

        async def capture_hook(state: object, config: object, store: object) -> dict:
            hook_calls.append(True)
            return {}

        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "hook test"},
            "id": "tc_hook",
            "type": "tool_call",
        }
        graph = self._compile_graph(
            create_fake_llm_with_tool_calls([tool_call, "All done."]),
            end_graph_hooks=[capture_hook],
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Do tool then finish")]},
            config={"configurable": {"thread_id": "t6"}},
        )

        assert len(hook_calls) >= 1, (
            "end_graph_hooks must fire after the full tool-call cycle ends."
        )

    @pytest.mark.asyncio
    async def test_tool_routes_to_tool_node_not_select_tools(self):
        """Regular tool calls route to 'tools' (DynamicToolNode), not 'select_tools'.

        With disable_retrieve_tools=True, 'select_tools' is not in the graph.
        A ToolMessage appearing proves DynamicToolNode ran (not select_tools).
        Fails if should_continue routes regular calls to 'select_tools'.
        """
        from tests.helpers import create_fake_llm_with_tool_calls

        tool_call = {
            "name": "dummy_tool",
            "args": {"query": "node check"},
            "id": "tc_node",
            "type": "tool_call",
        }
        graph = self._compile_graph(
            create_fake_llm_with_tool_calls([tool_call, "Done."])
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run it")]},
            config={"configurable": {"thread_id": "t7"}},
        )

        # A ToolMessage proves execution reached DynamicToolNode (tools node),
        # not select_tools (which would have re-entered the agent node instead).
        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "Tool call must route to 'tools' (DynamicToolNode) and produce a ToolMessage. "
            "If this fails, routing went to 'select_tools' or was dropped."
        )
