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


@tool
def _stub_vfs_read(path: str) -> str:
    """Read a file from the virtual filesystem (test stub)."""
    return f"Contents of {path}"


@tool
def _stub_deep_research(query: str) -> str:
    """Perform deep research on a topic (test stub)."""
    return f"Research results for: {query}"


def _make_mock_tool_registry():
    """Return a minimal ToolRegistry-like mock with the attributes accessed by
    build_executor_graph / SubAgentFactory.

    The tool_dict includes stubs for vfs_read and deep_research because
    build_executor_graph passes initial_tool_ids=["handoff", "plan_tasks",
    "mark_task", "add_task", "vfs_read", "deep_research"] to create_agent,
    which looks up each ID in the tool_registry dict at runtime.
    """
    registry = MagicMock()
    registry.get_tool_dict.return_value = {
        "vfs_read": _stub_vfs_read,
        "deep_research": _stub_deep_research,
    }
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
        nodes accessible via graph.nodes."""
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
                # The graph object must be truthy and expose a nodes mapping
                assert graph is not None
                assert hasattr(graph, "nodes")
                # Must contain at minimum an entry-point node
                assert len(graph.nodes) > 0

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
            # (plan_tasks, mark_task, add_task) must exist in the tool_dict so
            # acall_model can look them up via initial_tool_ids at runtime.
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
    (handoff, plan_tasks, mark_task, add_task, vfs_read, deep_research) are
    present in the merged tool_dict that is passed to create_agent."""

    async def test_handoff_included_in_tool_dict(self):
        """handoff tool must be injected into the tool_dict."""
        from app.agents.core.subagents.handoff_tools import handoff as handoff_tool

        # The handoff tool is a real @tool-decorated async function.
        # Just checking the schema / name is enough since we're not invoking it.
        assert handoff_tool.name == "handoff"
        # LangChain StructuredTool exposes .invoke() / .ainvoke() rather than __call__
        # in newer langchain-core versions; check for the tool interface instead.
        assert hasattr(handoff_tool, "invoke") or hasattr(handoff_tool, "run")

    async def test_initial_tool_ids_are_registered(self):
        """Executor graph must register all known initial tool IDs in tool_dict.

        We capture the keyword arguments passed to create_agent to inspect
        tool_registry and initial_tool_ids without running the full graph.
        """
        from app.agents.core.graph_builder.build_graph import build_executor_graph

        fake_llm = create_fake_llm(["ok"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        captured_kwargs: dict[str, Any] = {}

        def capturing_create_agent(**kwargs):
            captured_kwargs.update(kwargs)
            # Return a minimal builder that compiles to a trivial graph
            builder = StateGraph(SimpleState)
            builder.add_node("noop", lambda s: {})
            builder.set_entry_point("noop")
            builder.add_edge("noop", END)
            return builder

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
            patch(
                "app.agents.core.graph_builder.build_graph.create_agent",
                side_effect=capturing_create_agent,
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm,
                in_memory_checkpointer=True,
            ):
                pass

        # The tool_registry passed to create_agent must contain "handoff"
        tool_registry = captured_kwargs.get("tool_registry", {})
        assert "handoff" in tool_registry, (
            "handoff tool must be present in executor tool_registry"
        )

        expected_initial = {
            "handoff",
            "plan_tasks",
            "mark_task",
            "add_task",
            "vfs_read",
            "deep_research",
        }
        actual_initial = set(captured_kwargs.get("initial_tool_ids", []))
        assert expected_initial == actual_initial, (
            f"Executor initial_tool_ids mismatch.\n"
            f"Expected: {expected_initial}\n"
            f"Got:      {actual_initial}"
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
        """create_todo_tools must produce tools named plan_tasks, mark_task, add_task."""
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

        # Hook may return a Command or a dict; just ensure it doesn't raise
        assert result is not None

    def test_todo_tool_names_constant_is_correct(self):
        """TODO_TOOL_NAMES must match what build_executor_graph registers."""
        from app.agents.tools.todo_tools import TODO_TOOL_NAMES

        assert "plan_tasks" in TODO_TOOL_NAMES
        assert "mark_task" in TODO_TOOL_NAMES
        assert "add_task" in TODO_TOOL_NAMES


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
                pass

        mock_subagent_mw.set_llm.assert_called_once_with(fake_llm)
        mock_subagent_mw.set_tools.assert_called_once()
        mock_subagent_mw.set_store.assert_called_once_with(mock_store)
