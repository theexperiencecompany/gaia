"""Integration tests for the executor agent graph.

Tests real production code paths in the executor agent:
- build_executor_graph compilation (mocked I/O)
- select_tools / initial tool loading (handoff, todo, vfs_read wired into registry)
- tool execution through the compiled graph using FakeMessagesListChatModel
- todo pre-model hook invocation

All external I/O (LLM, DB, Composio, Redis, ChromaDB) is mocked so the
tests remain fast and require no running infrastructure, but the actual
production classes are imported and exercised directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore

from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls
from tests.integration.conftest import SimpleState


# ---------------------------------------------------------------------------
# Helpers / shared patches
# ---------------------------------------------------------------------------


def _make_stub_tool(name: str):
    """Create a minimal stub tool with the given name."""

    def _stub(input: str = "") -> str:  # noqa: A002
        return f"stub:{name}"

    _stub.__name__ = name
    _stub.__doc__ = f"Stub for {name}."
    return tool(_stub)


def _make_mock_tool_registry():
    """Return a minimal ToolRegistry-like mock with the attributes accessed by
    build_executor_graph / SubAgentFactory.

    Dynamically creates stub tools for every non-handoff, non-todo tool that
    appears in build_executor_graph's initial_tool_ids.  This keeps the test
    resilient to changes in the initial tool set (e.g. vfs_cmd being added or
    removed) without hard-coding specific tool names.
    """
    from app.agents.tools.todo_tools import TODO_TOOL_NAMES

    # Tools that build_executor_graph injects separately (handoff + todo tools)
    # and therefore do NOT need to come from the ToolRegistry mock.
    injected_by_graph = {"handoff"} | TODO_TOOL_NAMES

    # Read the actual initial_tool_ids from build_graph source so the mock
    # provides stubs for every tool the graph expects at runtime.
    import inspect
    from app.agents.core.graph_builder import build_graph as _bg_mod

    src = inspect.getsource(_bg_mod.build_executor_graph)
    # Extract the list literal assigned to initial_tool_ids
    import ast

    # Find the initial_tool_ids=[...] in the source
    idx = src.find("initial_tool_ids=")
    if idx != -1:
        bracket_start = src.index("[", idx)
        bracket_end = src.index("]", bracket_start) + 1
        raw_ids: list[str] = ast.literal_eval(src[bracket_start:bracket_end])
    else:
        raw_ids = []

    # Build stubs only for tools NOT injected by build_executor_graph itself
    tool_dict = {
        tid: _make_stub_tool(tid) for tid in raw_ids if tid not in injected_by_graph
    }

    registry = MagicMock()
    registry.get_tool_dict.return_value = tool_dict
    registry.get_category_by_space.return_value = None
    registry._categories = {}
    return registry


def _make_mock_store():
    """Return a real InMemoryStore so graph compilation succeeds."""
    return InMemoryStore()


def _make_dummy_retrieve_tools_fn():
    """Return a real async function that StructuredTool.from_function can introspect.

    When get_retrieve_tools_function() is patched, the returned value is passed
    as the `retrieve_tools_coroutine` arg to create_agent, which then calls
    StructuredTool.from_function(coroutine=<value>). StructuredTool inspects the
    function signature via inspect.signature(), which raises TypeError on AsyncMock.
    A real coroutine function avoids this.
    """

    async def _dummy_retrieve_tools(query: str = "") -> list:
        """Retrieve tools matching the query (test stub — always returns empty list)."""
        return []

    return _dummy_retrieve_tools


# ---------------------------------------------------------------------------
# Test: build_executor_graph compiles without error
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutorGraphCompiles:
    """Verify that build_executor_graph yields a compiled, callable graph."""

    async def test_executor_graph_compiles(self):
        """build_executor_graph must compile to a runnable graph with
        the expected structural nodes: 'agent', 'tools', and 'select_tools'.

        A graph missing any of these nodes would be structurally broken —
        e.g. removing 'tools' means tool calls are never executed, and
        removing 'select_tools' means the retrieval path is dead. Checking
        len > 0 alone would pass even a single dead-end stub node.
        """
        from app.agents.core.graph_builder.build_graph import build_executor_graph

        fake_llm = create_fake_llm(["Hello from executor"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_make_dummy_retrieve_tools_fn(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_pre_model_hook",
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ) as graph:
                node_names = set(graph.nodes)
                assert "agent" in node_names, (
                    "Compiled executor graph must contain an 'agent' node"
                )
                assert "tools" in node_names, (
                    "Compiled executor graph must contain a 'tools' node for tool execution"
                )
                assert "select_tools" in node_names, (
                    "Compiled executor graph must contain a 'select_tools' node for tool retrieval"
                )

    async def test_compiled_graph_is_invocable(self):
        """The compiled executor graph should accept ainvoke without raising."""
        from app.agents.core.graph_builder.build_graph import build_executor_graph

        fake_llm = create_fake_llm(["I am the executor"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_make_dummy_retrieve_tools_fn(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            # create_todo_tools and create_todo_pre_model_hook are NOT mocked here —
            # they are pure functions with no DB dependencies. The real todo tools
            # must exist in the tool_dict so acall_model can look them up via
            # initial_tool_ids at runtime.
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ) as graph:
                thread_id = str(uuid4())
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="what can you do?")]},
                    config={"configurable": {"thread_id": thread_id}},
                )
                assert result is not None
                assert "messages" in result


# ---------------------------------------------------------------------------
# Test: initial_tool_ids are wired into the tool registry
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSelectToolsNode:
    """Verify that the initial tool IDs specified in build_executor_graph
    are present in the merged tool_dict that is passed to create_agent."""

    async def test_handoff_included_in_tool_dict(self):
        """handoff tool must be registered in the compiled executor graph's tool node.

        This tests that build_executor_graph actually injects handoff into the
        DynamicToolNode's registry — not merely that the handoff tool object
        exists. Removing the 'tool_dict.update({"handoff": handoff_tool})' line
        from build_executor_graph would cause this test to fail.
        """
        from app.agents.core.graph_builder.build_graph import build_executor_graph
        from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode

        fake_llm = create_fake_llm(["Hello from executor"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_make_dummy_retrieve_tools_fn(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_pre_model_hook",
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ) as graph:
                tool_node = graph.nodes.get("tools")
                assert tool_node is not None, (
                    "Compiled executor graph must contain a 'tools' node"
                )
                # Unwrap to the underlying DynamicToolNode callable
                underlying = getattr(tool_node, "bound", tool_node)
                assert isinstance(underlying, DynamicToolNode), (
                    "The 'tools' node must be a DynamicToolNode"
                )
                assert "handoff" in underlying._tool_registry, (
                    "handoff must be registered in the executor graph's DynamicToolNode "
                    "tool registry; build_executor_graph is missing the handoff injection"
                )

    async def test_initial_tool_ids_are_registered(self):
        """All initial tool IDs expected by the executor graph must be present
        in the compiled graph's DynamicToolNode tool registry.

        The production flow in build_executor_graph passes initial_tool_ids to
        create_agent, which looks each ID up in tool_registry at model-call time
        (acall_model: `[tool_registry[id] for id in (initial_tool_ids or [])]`).
        If any ID is absent from the registry a KeyError is raised at runtime.
        This test verifies the registry is correctly populated for all expected
        initial tools so that lookup succeeds without patching create_agent away.
        """
        from app.agents.core.graph_builder.build_graph import build_executor_graph
        from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode

        fake_llm = create_fake_llm(["ok"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_make_dummy_retrieve_tools_fn(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_pre_model_hook",
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ) as graph:
                tool_node = graph.nodes.get("tools")
                assert tool_node is not None, (
                    "Compiled executor graph must contain a 'tools' node"
                )
                underlying = getattr(tool_node, "bound", tool_node)
                assert isinstance(underlying, DynamicToolNode), (
                    "The 'tools' node must be a DynamicToolNode"
                )
                registered_tool_ids = set(underlying._tool_registry.keys())

        # Every initial tool ID must be in the registry so that acall_model can
        # resolve `tool_registry[id]` without raising a KeyError at runtime.
        # Note: todo tools are mocked to return [] in this test, so todo tool
        # names are absent — only handoff + tools from mock registry are here.
        # Dynamically read what mock_registry provides to avoid hardcoding.
        mock_provided = set(mock_registry.get_tool_dict.return_value.keys())
        expected_in_registry = {"handoff"} | mock_provided
        missing = expected_in_registry - registered_tool_ids
        assert not missing, (
            f"The following initial tool IDs are missing from the executor graph's "
            f"DynamicToolNode registry and would cause a KeyError at runtime: {missing}"
        )


# ---------------------------------------------------------------------------
# Test: tool execution through a real graph (executor-like pattern)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolExecutionThroughRealGraph:
    """Build a minimal graph that mirrors the executor agent pattern and verify
    that a FakeMessagesListChatModel tool-call is executed by a real ToolNode."""

    @pytest.fixture
    def executor_tool(self):
        """A simple stand-in for any executor-tier tool."""

        @tool
        def lookup_data(query: str) -> str:
            """Look up data for a given query."""
            return f"Data result for: {query}"

        return lookup_data

    @pytest.fixture
    def executor_like_graph(self, executor_tool):
        """Build a model -> ToolNode -> model graph mimicking the executor pattern.

        The fake LLM first emits a tool call for lookup_data, then a final
        answer — exactly as the executor agent would behave.
        """
        tool_call = {
            "name": "lookup_data",
            "args": {"query": "test query"},
            "id": "call_exec_001",
            "type": "tool_call",
        }
        fake_llm = create_fake_llm_with_tool_calls([tool_call, "Found the answer."])

        def should_continue(state: SimpleState) -> str:
            last = state.messages[-1] if state.messages else None
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                return "tools"
            return "end"

        def model_node(state: SimpleState) -> dict[str, Any]:
            return {"messages": [fake_llm.invoke(state.messages)]}

        tool_node = ToolNode([executor_tool])

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

        return builder.compile(checkpointer=MemorySaver())

    async def test_tool_execution_through_real_graph(self, executor_like_graph):
        """Real ToolNode executes the tool call made by the fake LLM and
        injects the result as a ToolMessage back into the message list."""
        thread_id = str(uuid4())
        result = await executor_like_graph.ainvoke(
            {"messages": [HumanMessage(content="look up something")]},
            config={"configurable": {"thread_id": thread_id}},
        )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call_exec_001"
        assert "Data result for: test query" in tool_messages[0].content

    async def test_final_response_after_tool_execution(self, executor_like_graph):
        """Final AIMessage should follow the ToolMessage in execution order."""
        thread_id = str(uuid4())
        result = await executor_like_graph.ainvoke(
            {"messages": [HumanMessage(content="look up something")]},
            config={"configurable": {"thread_id": thread_id}},
        )

        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "Found the answer." in final.content

    async def test_checkpointed_state_contains_tool_results(self, executor_like_graph):
        """After invocation, get_state should return the full message chain
        including ToolMessages from tool execution."""
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        await executor_like_graph.ainvoke(
            {"messages": [HumanMessage(content="look up something")]},
            config=config,
        )

        state = await executor_like_graph.aget_state(config)
        tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_msgs) >= 1, "Checkpointed state must include ToolMessages"


# ---------------------------------------------------------------------------
# Test: todo pre-model hook is created and callable
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTodoPremModelHook:
    """Verify that create_todo_pre_model_hook returns a callable that can be
    invoked with a graph state dict (no external deps needed)."""

    def test_create_todo_pre_model_hook_returns_callable(self):
        """create_todo_pre_model_hook must return a callable pre-model hook."""
        from app.agents.tools.todo_tools import create_todo_pre_model_hook

        hook = create_todo_pre_model_hook(source="executor")
        assert callable(hook), "todo pre-model hook must be callable"

    def test_todo_tools_are_created_with_correct_names(self):
        """create_todo_tools must produce tools whose names match TODO_TOOL_NAMES."""
        from app.agents.tools.todo_tools import TODO_TOOL_NAMES, create_todo_tools

        tools = create_todo_tools(source="executor")
        tool_names = {t.name for t in tools}

        assert tool_names == TODO_TOOL_NAMES, (
            f"Expected todo tools {TODO_TOOL_NAMES}, got {tool_names}"
        )

    def test_todo_hook_injects_system_message(self):
        """The todo pre-model hook must inject a system message into state
        when todos are present in the state."""
        from app.agents.tools.todo_tools import create_todo_pre_model_hook

        hook = create_todo_pre_model_hook(source="executor")

        # Build a minimal state dict with a todo item and a plain SystemMessage
        state = {
            "messages": [
                SystemMessage(content="You are an executor agent."),
                HumanMessage(content="Do the work"),
            ],
            "todos": [
                {
                    "id": "todo-1",
                    "content": "Step 1: complete the task",
                    "status": "pending",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        }
        config = {"configurable": {"thread_id": str(uuid4())}}
        store = _make_mock_store()

        # The hook is synchronous: signature is (state, config, store) -> State
        result = hook(state, config, store)

        # The hook must return a state dict (not None, not raise).
        # More importantly, it must have injected todo context into the
        # SystemMessage: the returned messages list must contain a SystemMessage
        # whose content includes the formatted todo item and the TODO_SYSTEM_PROMPT
        # marker text. A vacuous `result is not None` check would pass even if
        # the hook silently returned the input state unchanged or an empty dict.
        assert isinstance(result, dict), "todo pre-model hook must return a state dict"
        messages = result.get("messages", [])
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        assert system_messages, (
            "todo pre-model hook must produce at least one SystemMessage in state"
        )
        combined_content = "\n".join(
            m.content for m in system_messages if isinstance(m.content, str)
        )
        assert "plan_tasks" in combined_content, (
            "todo pre-model hook must inject TODO_SYSTEM_PROMPT (which references "
            "'plan_tasks') into the SystemMessage content"
        )
        assert "Step 1: complete the task" in combined_content, (
            "todo pre-model hook must inject the formatted todo item content into "
            "the SystemMessage so the LLM sees the current task list"
        )

    def test_todo_tool_names_constant_is_correct(self):
        """TODO_TOOL_NAMES must match the actual tools returned by create_todo_tools."""
        from app.agents.tools.todo_tools import TODO_TOOL_NAMES, create_todo_tools

        tools = create_todo_tools(source="executor")
        actual_names = {t.name for t in tools}
        assert TODO_TOOL_NAMES == actual_names, (
            f"TODO_TOOL_NAMES {TODO_TOOL_NAMES} does not match "
            f"tools from create_todo_tools: {actual_names}"
        )
        # plan_tasks must always be present
        assert "plan_tasks" in TODO_TOOL_NAMES


# ---------------------------------------------------------------------------
# Test: SubagentMiddleware wiring in executor graph
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutorSubagentMiddlewareWiring:
    """Verify that build_executor_graph correctly wires the SubagentMiddleware
    with llm, tools, and store when one is present in the middleware list."""

    async def test_subagent_middleware_receives_llm_and_tools(self):
        """If SubagentMiddleware is in the executor middleware stack,
        set_llm / set_tools / set_store must each be called exactly once."""
        from app.agents.core.graph_builder.build_graph import build_executor_graph
        from app.agents.middleware import SubagentMiddleware

        fake_llm = create_fake_llm(["executor response"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        mock_subagent_mw = MagicMock(spec=SubagentMiddleware)
        mock_subagent_mw.set_llm = MagicMock()
        mock_subagent_mw.set_tools = MagicMock()
        mock_subagent_mw.set_store = MagicMock()

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_make_dummy_retrieve_tools_fn(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[mock_subagent_mw],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_todo_pre_model_hook",
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ):
                # Enter the context manager to trigger graph initialisation;
                # assertions are made on the mocks after the block exits.
                pass

        mock_subagent_mw.set_llm.assert_called_once_with(fake_llm)
        mock_subagent_mw.set_tools.assert_called_once()
        mock_subagent_mw.set_store.assert_called_once_with(mock_store)
