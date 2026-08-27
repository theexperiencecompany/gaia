"""
Tests for the agent routing logic (should_continue) in create_agent.

The should_continue function is a closure inside create_agent. These tests
verify routing behavior by calling create_agent with a minimal LLM/tool setup
and inspecting what happens when the compiled graph is invoked with states
that have or don't have tool_calls on the last AIMessage.
"""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
import pytest

from app.constants.llm import COMPLETION_NUDGE_MESSAGE, MAX_COMPLETION_NUDGES
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
        assert len(agent_branches) > 0, "Expected at least one branch condition on 'agent' node."

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
            BindableToolsFakeModel(responses=[AIMessage(content="No tools needed.", tool_calls=[])])
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config={"configurable": {"thread_id": "t4"}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, "Empty tool_calls list must not route to tool node."

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
            f"Final AIMessage content must match the fake LLM response. Got: {final_ai.content!r}"
        )


class TestCompletionNudgeWiring:
    """The executor's harness-owned completion, from the graph's side.

    ``tests/unit/agents/middleware/test_completion.py`` proves the predicates and
    ``tests/integration/agents/test_harness_completion.py`` proves the end-to-end
    journey. Neither pins the wiring in ``create_agent`` that connects them: that a
    ``nudge_continue`` node exists, that its edge loops back to the agent, and that
    the nudge is only reachable for an executor with work left. A rename or a
    dropped edge here leaves the guard inert while every other tier stays green.
    """

    def _compile_executor(self, llm, *, require_finish_to_end: bool = True):
        from langgraph.checkpoint.memory import MemorySaver

        builder = create_agent(
            llm=llm,
            tool_registry=_build_minimal_registry(),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="executor_agent",
            require_finish_to_end=require_finish_to_end,
        )
        return builder.compile(checkpointer=MemorySaver())

    @staticmethod
    def _nudges(result) -> list[str]:
        """The nudge turns the harness injected into this run."""
        return [
            m.content
            for m in result["messages"]
            if isinstance(m, HumanMessage) and m.content == COMPLETION_NUDGE_MESSAGE
        ]

    @pytest.mark.asyncio
    async def test_an_executor_stopping_with_no_work_done_is_nudged_back_to_the_agent(self):
        """A plain-text stop after zero tool calls is the "one lookup then assert a
        conclusion" ending the guard exists to refuse. The nudge has to reach the
        model, which only happens if the node is registered AND its edge loops back."""
        graph = self._compile_executor(
            BindableToolsFakeModel(
                responses=[AIMessage(content="All done."), AIMessage(content="Actually done.")]
            )
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="triage my inbox")]},
            config={"configurable": {"thread_id": "nudge-1"}},
        )

        assert self._nudges(result) == [COMPLETION_NUDGE_MESSAGE]
        assert result["messages"][-1].content == "Actually done."

    @pytest.mark.asyncio
    async def test_the_nudge_is_bounded_so_a_tool_free_answer_cannot_loop(self):
        """MAX_COMPLETION_NUDGES is the only thing between a genuinely tool-free
        answer and an infinite agent/nudge cycle."""
        graph = self._compile_executor(
            BindableToolsFakeModel(responses=[AIMessage(content=f"Reply {i}.") for i in range(6)])
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="what is 2 + 2?")]},
            config={"configurable": {"thread_id": "nudge-2"}},
        )

        assert len(self._nudges(result)) == MAX_COMPLETION_NUDGES

    @pytest.mark.asyncio
    async def test_an_agent_that_did_not_opt_in_is_never_nudged(self):
        """Comms passes require_finish_to_end=False and must end on plain text as
        before — the guard is executor-only, not a global tax on every graph."""
        graph = self._compile_executor(
            BindableToolsFakeModel(responses=[AIMessage(content="Here you go.")]),
            require_finish_to_end=False,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="say hi")]},
            config={"configurable": {"thread_id": "nudge-3"}},
        )

        assert self._nudges(result) == []
        assert result["messages"][-1].content == "Here you go."

    @pytest.mark.asyncio
    async def test_a_finished_run_is_not_taxed_with_a_nudge(self):
        """Work demonstrably done — an open todo is absent and the tool-call floor is
        met — must end on the first plain-text reply, or every completed executor run
        pays an extra model call."""
        graph = self._compile_executor(
            BindableToolsFakeModel(responses=[AIMessage(content="Finished.")])
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content="triage my inbox"),
                    AIMessage(content=""),
                    ToolMessage(content="ok", tool_call_id="c1"),
                    AIMessage(content=""),
                    ToolMessage(content="ok", tool_call_id="c2"),
                ],
                "todos": [],
            },
            config={"configurable": {"thread_id": "nudge-4"}},
        )

        assert self._nudges(result) == []

    def test_the_sync_graph_path_nudges_too(self):
        """``invoke`` runs the sync twins of the nudge node and the routing closure.
        A graph wired only for the async path leaves every synchronous caller — the
        dev direct-invocation endpoints, scripts — with the guard switched off."""
        graph = self._compile_executor(
            BindableToolsFakeModel(
                responses=[AIMessage(content="All done."), AIMessage(content="Actually done.")]
            )
        )

        result = graph.invoke(
            {"messages": [HumanMessage(content="triage my inbox")]},
            config={"configurable": {"thread_id": "nudge-sync"}},
        )

        assert self._nudges(result) == [COMPLETION_NUDGE_MESSAGE]

    @pytest.mark.asyncio
    async def test_the_guard_is_off_unless_an_agent_opts_in(self):
        """``require_finish_to_end`` defaults to off. Flipping the default would put
        every comms turn through the executor's completion check."""
        from langgraph.checkpoint.memory import MemorySaver

        builder = create_agent(
            llm=BindableToolsFakeModel(responses=[AIMessage(content="Here you go.")]),
            tool_registry=_build_minimal_registry(),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="comms_agent",
        )
        graph = builder.compile(checkpointer=MemorySaver())

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="say hi")]},
            config={"configurable": {"thread_id": "nudge-default"}},
        )

        assert self._nudges(result) == []

    @pytest.mark.asyncio
    async def test_the_agent_call_is_not_metered_twice(self):
        """LLMAccountingMiddleware already charges the graph's own model call.
        Metering it here as auxiliary spend too books every agent turn a second
        time, which lands in usage_daily as real money the user never spent."""
        with patch(
            "app.override.langgraph_bigtool.create_agent.ainvoke_llm",
            new=AsyncMock(return_value=AIMessage(content="done")),
        ) as mock_invoke:
            graph = self._compile_executor(
                BindableToolsFakeModel(responses=[AIMessage(content="done")]),
                require_finish_to_end=False,
            )
            await graph.ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config={"configurable": {"thread_id": "meter-1"}},
            )

        assert mock_invoke.call_args.kwargs["meter_auxiliary"] is False

    def test_the_nudge_node_is_a_declared_routing_destination(self):
        """should_continue can only return "nudge_continue" if the branch declares it;
        an undeclared destination is a runtime error the moment the guard fires."""
        builder = create_agent(
            llm=_make_mock_llm(AIMessage(content="done")),
            tool_registry=_build_minimal_registry(),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool"],
            agent_name="executor_agent",
            require_finish_to_end=True,
        )

        assert "nudge_continue" in _get_agent_branch_ends(builder).values()


class TestRetrievedToolDiscoveryRendering:
    """``select_tools`` turns a retrieve_tools call into the ToolMessage the model
    reads next. This PR added ``response_text``: a block the retriever pre-renders
    so the discovery listing reaches the model verbatim instead of being rebuilt
    from ids. Nothing exercised that path, so every mutation of the accumulation
    and the hand-off to ``format_selected_tools`` survived.
    """

    @staticmethod
    def _retrieving_model() -> BindableToolsFakeModel:
        """A model that asks for tool discovery once, then answers."""
        return BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "retrieve_tools",
                            "args": {"query": "email"},
                            "id": "call_retrieve_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Found them."),
            ]
        )

    def _compile(self, retrieve_coroutine):
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.store.memory import InMemoryStore

        # StructuredTool takes its name from the sync function, and the model's
        # call has to match it — the graph rejects anything not bound by name.
        def retrieve_tools(query: str) -> list[str]:
            """Retrieve tools matching the query."""
            raise AssertionError("the async graph path must use the coroutine")

        builder = create_agent(
            llm=self._retrieving_model(),
            tool_registry=_build_minimal_registry(),
            retrieve_tools_function=retrieve_tools,
            retrieve_tools_coroutine=retrieve_coroutine,
            initial_tool_ids=[],
            agent_name="executor_agent",
        )
        return builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

    @staticmethod
    def _discovery_message(result) -> str:
        """The ToolMessage answering the retrieve_tools call."""
        replies = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and m.tool_call_id == "call_retrieve_1"
        ]
        assert len(replies) == 1
        return replies[0].content

    @pytest.mark.asyncio
    async def test_a_prerendered_discovery_block_reaches_the_model_verbatim(self):
        """The retriever renders the listing (icons, grouping, per-tool blurbs); if
        the pre-rendered text is dropped the model gets a bare id list instead."""

        async def _retrieve(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": "## Email tools\n- dummy_tool — does the thing",
            }

        graph = self._compile(_retrieve)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-1", "user_id": "user-1"}},
        )

        assert self._discovery_message(result) == "## Email tools\n- dummy_tool — does the thing"

    @pytest.mark.asyncio
    async def test_an_empty_prerendered_block_falls_back_to_the_built_listing(self):
        """An empty string is not a rendering — it must not replace the listing with
        nothing, which would leave the model with no discovery result at all."""

        async def _retrieve(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": "",
            }

        graph = self._compile(_retrieve)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-2", "user_id": "user-1"}},
        )

        assert "dummy_tool" in self._discovery_message(result)

    def test_the_sync_graph_path_renders_the_prerendered_block_too(self):
        """``select_tools`` is the sync twin of ``aselect_tools`` and is what
        ``graph.invoke`` runs. The two assemble the same ToolMessage, so a fix
        applied to one and not the other splits the discovery listing by caller."""
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.store.memory import InMemoryStore

        def retrieve_tools(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": "## Email tools\n- dummy_tool — does the thing",
            }

        builder = create_agent(
            llm=self._retrieving_model(),
            tool_registry=_build_minimal_registry(),
            retrieve_tools_function=retrieve_tools,
            initial_tool_ids=[],
            agent_name="executor_agent",
        )
        graph = builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

        result = graph.invoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-sync", "user_id": "user-1"}},
        )

        assert self._discovery_message(result) == "## Email tools\n- dummy_tool — does the thing"

    def test_the_sync_path_falls_back_when_the_block_is_empty(self):
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.store.memory import InMemoryStore

        def retrieve_tools(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": "",
            }

        builder = create_agent(
            llm=self._retrieving_model(),
            tool_registry=_build_minimal_registry(),
            retrieve_tools_function=retrieve_tools,
            initial_tool_ids=[],
            agent_name="executor_agent",
        )
        graph = builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

        result = graph.invoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-sync-2", "user_id": "user-1"}},
        )

        assert "dummy_tool" in self._discovery_message(result)

    @pytest.mark.asyncio
    async def test_a_non_string_prerendered_block_is_refused(self):
        """The retriever is pluggable, so ``response_text`` can come back any shape.
        Anything that is not a string must fall back to the built listing rather
        than be handed to ToolMessage, which would put a dict where the model
        expects prose."""

        async def _retrieve(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": {"unexpected": "shape"},
            }

        graph = self._compile(_retrieve)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-4", "user_id": "user-1"}},
        )

        assert "dummy_tool" in self._discovery_message(result)

    def test_the_sync_path_also_refuses_a_non_string_block(self):
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.store.memory import InMemoryStore

        def retrieve_tools(query: str) -> dict:
            """Retrieve tools matching the query."""
            return {
                "tools_to_bind": ["dummy_tool"],
                "response": ["dummy_tool"],
                "response_text": {"unexpected": "shape"},
            }

        builder = create_agent(
            llm=self._retrieving_model(),
            tool_registry=_build_minimal_registry(),
            retrieve_tools_function=retrieve_tools,
            initial_tool_ids=[],
            agent_name="executor_agent",
        )
        graph = builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

        result = graph.invoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-sync-3", "user_id": "user-1"}},
        )

        assert "dummy_tool" in self._discovery_message(result)

    @pytest.mark.asyncio
    async def test_a_retriever_returning_a_plain_list_still_renders(self):
        """The legacy shape: no dict, no pre-rendered text, just ids."""

        async def _retrieve(query: str) -> list[str]:
            """Retrieve tools matching the query."""
            return ["dummy_tool"]

        graph = self._compile(_retrieve)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="find me email tools")]},
            config={"configurable": {"thread_id": "retr-3", "user_id": "user-1"}},
        )

        assert "dummy_tool" in self._discovery_message(result)
