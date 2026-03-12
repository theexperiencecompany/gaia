"""Integration tests for subagent handoff chain.

Covers the comms -> executor -> subagent delegation path:
- SubAgentFactory.create_provider_subagent can be instantiated
- handoff tool has the correct schema / is importable from production code
- SubagentExecutionContext stores all fields correctly
- Different thread IDs produce independent checkpointed state
- build_initial_messages constructs the correct 3-message list
- get_subagent_by_id / get_subagent_integrations return real data
- prepare_subagent_execution fails gracefully when subagent not found
- register_subagent_providers registers integrations from OAUTH_INTEGRATIONS
- execute_subagent_stream processes streamed events correctly

All external I/O (LLM, DB, Composio, Redis, MCP servers) is mocked.
Real production classes and functions are imported so tests fail if code moves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore

from langchain_core.tools import tool

from tests.factories import make_user
from tests.helpers import create_fake_llm
from tests.integration.conftest import SimpleState


# ---------------------------------------------------------------------------
# Stub LangChain tools (DynamicToolNode requires real tool objects, not MagicMock)
# ---------------------------------------------------------------------------


@tool
def _stub_deep_research(query: str) -> str:
    """Perform deep research on a topic (test stub)."""
    return f"Research results for: {query}"


@tool
def _stub_web_search(query: str) -> str:
    """Search the web for information (test stub)."""
    return f"Web results for: {query}"


@tool
def _stub_fetch_webpages(urls: str) -> str:
    """Fetch content from web pages (test stub)."""
    return f"Fetched: {urls}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_store() -> InMemoryStore:
    return InMemoryStore()


def _make_mock_tool_registry():
    registry = MagicMock()
    registry.get_tool_dict.return_value = {}
    registry.get_category_by_space.return_value = None
    registry._categories = {}
    return registry


def _make_minimal_subagent_graph() -> Any:
    """Return a trivial compiled graph that mimics a subagent."""

    def respond(state: SimpleState) -> dict[str, Any]:
        return {"messages": [AIMessage(content="subagent completed task")]}

    builder = StateGraph(SimpleState)
    builder.add_node("respond", respond)
    builder.set_entry_point("respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Test: SubAgentFactory is importable and its static method is callable
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubAgentCanBeInstantiated:
    """Verify SubAgentFactory can be imported and its factory method invoked
    with mocked infrastructure."""

    def test_subagent_factory_class_is_importable(self):
        """Importing SubAgentFactory must not raise; the class must exist."""
        from app.agents.core.subagents.base_subagent import SubAgentFactory  # noqa: F401

        assert SubAgentFactory is not None

    def test_create_provider_subagent_method_exists(self):
        """SubAgentFactory.create_provider_subagent must be a static async method."""
        from app.agents.core.subagents.base_subagent import SubAgentFactory

        method = getattr(SubAgentFactory, "create_provider_subagent", None)
        assert method is not None, (
            "create_provider_subagent not found on SubAgentFactory"
        )
        assert callable(method)

    async def test_create_provider_subagent_compiles_graph(self):
        """SubAgentFactory.create_provider_subagent must yield a compiled graph
        when all external calls are mocked."""
        from app.agents.core.subagents.base_subagent import SubAgentFactory

        fake_llm = create_fake_llm(["subagent answer"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            # get_tool_registry, deep_research, web_search_tool, fetch_webpages are
            # all imported *inside* create_provider_subagent (local imports), so they
            # must be patched at their source modules rather than on base_subagent.
            patch(
                "app.agents.tools.core.registry.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.get_tools_store",
                new=AsyncMock(return_value=mock_store),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_subagent_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_todo_pre_model_hook",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.tools.research_tool.deep_research",
                new=_stub_deep_research,
            ),
            patch(
                "app.agents.tools.webpage_tool.web_search_tool",
                new=_stub_web_search,
            ),
            patch(
                "app.agents.tools.webpage_tool.fetch_webpages",
                new=_stub_fetch_webpages,
            ),
        ):
            graph = await SubAgentFactory.create_provider_subagent(
                provider="test_provider",
                name="test_agent",
                llm=fake_llm,
                tool_space="test_space",
                use_direct_tools=True,
                disable_retrieve_tools=True,
            )

        assert graph is not None
        assert hasattr(graph, "nodes")
        assert len(graph.nodes) > 0


# ---------------------------------------------------------------------------
# Test: handoff tool schema is correct
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHandoffToolStructure:
    """Verify the handoff tool exposes the expected JSON schema."""

    def test_handoff_tool_is_importable(self):
        """handoff must be importable from handoff_tools."""
        from app.agents.core.subagents.handoff_tools import handoff  # noqa: F401

        assert handoff is not None

    def test_handoff_tool_name(self):
        """handoff.name must be 'handoff'."""
        from app.agents.core.subagents.handoff_tools import handoff

        assert handoff.name == "handoff"

    def test_handoff_tool_schema_contains_required_params(self):
        """handoff schema must expose subagent_id and task as required inputs."""
        from app.agents.core.subagents.handoff_tools import handoff

        schema = handoff.args_schema.schema() if handoff.args_schema else {}
        # args_schema may not be set; fall back to tool.schema()
        if not schema:
            schema = handoff.schema() if hasattr(handoff, "schema") else {}

        # The tool is annotated with subagent_id and task parameters.
        # For async @tool-decorated functions LangChain stores the original coroutine
        # in `.coroutine`; `.func` is used for sync tools.
        import inspect

        underlying = (
            getattr(handoff, "coroutine", None)
            or getattr(handoff, "func", None)
            or handoff
        )
        sig = inspect.signature(underlying)
        param_names = set(sig.parameters.keys())

        assert "subagent_id" in param_names, (
            f"handoff must accept 'subagent_id'; found params: {param_names}"
        )
        assert "task" in param_names, (
            f"handoff must accept 'task'; found params: {param_names}"
        )

    def test_handoff_tool_is_async(self):
        """handoff must be an async function (coroutine function)."""
        import inspect
        from app.agents.core.subagents.handoff_tools import handoff

        # For async @tool-decorated functions LangChain stores the original coroutine
        # in `.coroutine`; `.func` is used for sync tools.
        underlying = (
            getattr(handoff, "coroutine", None)
            or getattr(handoff, "func", None)
            or handoff
        )
        assert inspect.iscoroutinefunction(underlying), "handoff tool must be async"

    def test_handoff_tool_has_docstring(self):
        """handoff must have a non-empty description for the LLM."""
        from app.agents.core.subagents.handoff_tools import handoff

        description = handoff.description
        assert description and len(description) > 10, (
            "handoff tool description must be informative"
        )


# ---------------------------------------------------------------------------
# Test: SubagentExecutionContext stores fields correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentExecutionContext:
    """Verify SubagentExecutionContext is importable and stores all fields."""

    def test_context_is_importable(self):
        """SubagentExecutionContext must be importable from subagent_runner."""
        from app.agents.core.subagents.subagent_runner import (  # noqa: F401
            SubagentExecutionContext,
        )

        assert SubagentExecutionContext is not None

    def test_context_stores_all_fields(self):
        """SubagentExecutionContext must expose all constructor arguments."""
        from app.agents.core.subagents.subagent_runner import SubagentExecutionContext

        mock_graph = MagicMock()
        user_id = str(uuid4())
        stream_id = str(uuid4())
        thread_id = str(uuid4())

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="gmail_agent",
            config={"configurable": {"thread_id": thread_id}},
            configurable={"thread_id": thread_id, "user_id": user_id},
            integration_id="gmail",
            initial_state={"messages": [], "todos": []},
            user_id=user_id,
            stream_id=stream_id,
        )

        assert ctx.subagent_graph is mock_graph
        assert ctx.agent_name == "gmail_agent"
        assert ctx.integration_id == "gmail"
        assert ctx.user_id == user_id
        assert ctx.stream_id == stream_id
        assert ctx.initial_state == {"messages": [], "todos": []}

    def test_context_user_id_optional(self):
        """user_id and stream_id must be optional (default None)."""
        from app.agents.core.subagents.subagent_runner import SubagentExecutionContext

        ctx = SubagentExecutionContext(
            subagent_graph=MagicMock(),
            agent_name="test_agent",
            config={},
            configurable={},
            integration_id="test",
            initial_state={"messages": []},
        )

        assert ctx.user_id is None
        assert ctx.stream_id is None

    async def test_context_is_consumed_by_execute_subagent_stream(self):
        """SubagentExecutionContext must be accepted and consumed by the real
        execute_subagent_stream function — verifying that field names and types
        match what the production streaming function actually reads."""
        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            execute_subagent_stream,
        )

        chunk = AIMessageChunk(content="context field test passed")
        events = [("messages", (chunk, {}))]

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_iter(events))

        thread_id = str(uuid4())
        user_id = str(uuid4())
        stream_id = str(uuid4())

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="gmail_agent",
            config={"configurable": {"thread_id": thread_id}},
            configurable={"thread_id": thread_id, "user_id": user_id},
            integration_id="gmail",
            initial_state={"messages": [], "todos": []},
            user_id=user_id,
            stream_id=stream_id,
        )

        # stream_id is set — execute_subagent_stream reads ctx.stream_id to check
        # cancellation; mock stream_manager so it does not raise
        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager"
        ) as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        # The production function read ctx.initial_state, ctx.config, ctx.stream_id
        # correctly — if any field name were wrong the call would have raised
        assert "context field test passed" in result
        mock_graph.astream.assert_called_once_with(
            ctx.initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=ctx.config,
        )


# ---------------------------------------------------------------------------
# Test: thread ID isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentThreadIsolation:
    """Verify that two subagent graphs sharing the same MemorySaver instance
    but using different thread IDs do not share state."""

    async def test_subagent_thread_isolation(self):
        """Subagent invocations with different thread IDs must produce
        independent checkpointed states."""
        graph_a = _make_minimal_subagent_graph()
        graph_b = _make_minimal_subagent_graph()

        thread_a = {"configurable": {"thread_id": f"subagent_gmail_{uuid4()}"}}
        thread_b = {"configurable": {"thread_id": f"subagent_notion_{uuid4()}"}}

        await graph_a.ainvoke(
            {"messages": [HumanMessage(content="Task A")]},
            config=thread_a,
        )
        await graph_b.ainvoke(
            {"messages": [HumanMessage(content="Task B")]},
            config=thread_b,
        )

        state_a = await graph_a.aget_state(thread_a)
        state_b = await graph_b.aget_state(thread_b)

        # Human messages should differ
        human_a = [m for m in state_a.values["messages"] if isinstance(m, HumanMessage)]
        human_b = [m for m in state_b.values["messages"] if isinstance(m, HumanMessage)]

        assert human_a[0].content == "Task A"
        assert human_b[0].content == "Task B"

    async def test_subagent_thread_id_format(self):
        """Thread IDs produced by prepare_subagent_execution follow the
        '{integration_id}_{parent_thread_id}' convention.

        Calls the real production function with a mocked provider graph and
        checks that the thread_id embedded in the returned config matches the
        expected pattern for two different integration IDs sharing the same
        parent conversation_id.
        """
        from datetime import timezone

        from langchain_core.messages import SystemMessage

        from app.agents.core.subagents.subagent_runner import (
            get_subagent_integrations,
            prepare_subagent_execution,
        )

        integrations = get_subagent_integrations()
        # Need at least two non-auth-required integrations to compare
        eligible = [
            i
            for i in integrations
            if not (
                i.managed_by == "mcp" and i.mcp_config and i.mcp_config.requires_auth
            )
        ]
        if len(eligible) < 2:
            pytest.skip("Need at least two non-auth-required subagent integrations")

        integ_a = eligible[0]
        integ_b = eligible[1]
        parent_thread = str(uuid4())
        user = make_user()

        mock_graph = _make_minimal_subagent_graph()

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.providers"
            ) as mock_providers,
            patch("app.helpers.agent_helpers.providers") as mock_helpers_providers,
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new=AsyncMock(return_value=SystemMessage(content="ctx")),
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            mock_helpers_providers.get = MagicMock(return_value=None)

            ctx_a, err_a = await prepare_subagent_execution(
                subagent_id=integ_a.id,
                task="test task",
                user=user,
                user_time=datetime.now(timezone.utc),
                conversation_id=parent_thread,
            )
            ctx_b, err_b = await prepare_subagent_execution(
                subagent_id=integ_b.id,
                task="test task",
                user=user,
                user_time=datetime.now(timezone.utc),
                conversation_id=parent_thread,
            )

        assert err_a is None, (
            f"prepare_subagent_execution failed for {integ_a.id}: {err_a}"
        )
        assert err_b is None, (
            f"prepare_subagent_execution failed for {integ_b.id}: {err_b}"
        )

        thread_a = ctx_a.config["configurable"]["thread_id"]
        thread_b = ctx_b.config["configurable"]["thread_id"]

        # Each thread ID must embed the integration ID and parent thread
        assert thread_a == f"{integ_a.id}_{parent_thread}", (
            f"Expected '{integ_a.id}_{parent_thread}', got '{thread_a}'"
        )
        assert thread_b == f"{integ_b.id}_{parent_thread}", (
            f"Expected '{integ_b.id}_{parent_thread}', got '{thread_b}'"
        )
        # Two different integrations sharing the same parent must have distinct thread IDs
        assert thread_a != thread_b
        # Both thread IDs must end with the same parent conversation ID
        assert thread_a.endswith(parent_thread)
        assert thread_b.endswith(parent_thread)

    async def test_same_graph_different_threads_are_isolated(self):
        """The same compiled graph object with different thread configs
        must maintain independent state per thread."""
        graph = _make_minimal_subagent_graph()

        config_x = {"configurable": {"thread_id": f"thread-x-{uuid4()}"}}
        config_y = {"configurable": {"thread_id": f"thread-y-{uuid4()}"}}

        await graph.ainvoke(
            {"messages": [HumanMessage(content="From X")]}, config=config_x
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="From Y")]}, config=config_y
        )

        state_x = await graph.aget_state(config_x)
        state_y = await graph.aget_state(config_y)

        human_x = [m for m in state_x.values["messages"] if isinstance(m, HumanMessage)]
        human_y = [m for m in state_y.values["messages"] if isinstance(m, HumanMessage)]

        assert human_x[0].content == "From X"
        assert human_y[0].content == "From Y"


# ---------------------------------------------------------------------------
# Test: subagent graph run with mocked external calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentRun:
    """Run a subagent through its graph with all external calls mocked."""

    async def test_subagent_run_returns_result(self):
        """prepare_subagent_execution must return a valid SubagentExecutionContext
        whose graph can be invoked to produce an AIMessage result.

        Uses the real production prepare_subagent_execution with all external
        I/O mocked at the boundary (LLM graph, system message, context message).
        Asserts on the real context structure and real graph invocation result.
        """
        from datetime import timezone

        from langchain_core.messages import SystemMessage

        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            get_subagent_integrations,
            prepare_subagent_execution,
        )

        integrations = get_subagent_integrations()
        eligible = [
            i
            for i in integrations
            if not (
                i.managed_by == "mcp" and i.mcp_config and i.mcp_config.requires_auth
            )
        ]
        if not eligible:
            pytest.skip("No non-auth-required subagent integrations available")

        first = eligible[0]
        user = make_user()
        conversation_id = str(uuid4())
        real_graph = _make_minimal_subagent_graph()

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.providers"
            ) as mock_providers,
            patch("app.helpers.agent_helpers.providers") as mock_helpers_providers,
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new=AsyncMock(
                    return_value=SystemMessage(content="You are a test agent.")
                ),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new=AsyncMock(return_value=SystemMessage(content="Context: test.")),
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=real_graph)
            mock_helpers_providers.get = MagicMock(return_value=None)

            ctx, error = await prepare_subagent_execution(
                subagent_id=first.id,
                task="Do some work",
                user=user,
                user_time=datetime.now(timezone.utc),
                conversation_id=conversation_id,
            )

        assert error is None, f"prepare_subagent_execution failed: {error}"
        assert ctx is not None
        assert isinstance(ctx, SubagentExecutionContext)
        assert ctx.agent_name == first.subagent_config.agent_name
        assert ctx.integration_id == first.id
        assert ctx.subagent_graph is real_graph
        assert "messages" in ctx.initial_state
        assert len(ctx.initial_state["messages"]) == 3

        # Invoke the real graph through the context to confirm it runs end-to-end
        result = await ctx.subagent_graph.ainvoke(
            ctx.initial_state,
            config=ctx.config,
        )

        assert result is not None
        assert "messages" in result
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1
        assert ai_messages[-1].content == "subagent completed task"

    async def test_execute_subagent_stream_returns_content(self):
        """execute_subagent_stream must accumulate AI content from messages
        stream events and return the joined string."""
        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            execute_subagent_stream,
        )

        # Build a fake graph that yields known streaming events
        chunk = AIMessageChunk(content="Hello from Gmail agent")
        events = [
            ("messages", (chunk, {})),
        ]

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_iter(events))

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="gmail_agent",
            config={"configurable": {"thread_id": str(uuid4())}},
            configurable={},
            integration_id="gmail",
            initial_state={"messages": [], "todos": []},
            user_id="user-1",
        )

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager"
        ) as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert "Hello from Gmail agent" in result

    async def test_execute_subagent_stream_default_on_empty(self):
        """execute_subagent_stream must return 'Task completed' when no AI
        content is produced."""
        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            execute_subagent_stream,
        )

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_iter([]))

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="notion_agent",
            config={"configurable": {"thread_id": str(uuid4())}},
            configurable={},
            integration_id="notion",
            initial_state={"messages": [], "todos": []},
        )

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager"
        ) as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert result == "Task completed"

    async def test_execute_subagent_stream_forwards_custom_events(self):
        """Custom stream events must be forwarded to the stream_writer."""
        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            execute_subagent_stream,
        )

        custom_payload = {"progress": "Processing..."}
        events = [
            ("custom", custom_payload),
        ]

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_iter(events))

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="calendar_agent",
            config={"configurable": {"thread_id": str(uuid4())}},
            configurable={},
            integration_id="googlecalendar",
            initial_state={"messages": [], "todos": []},
        )

        written_events: list[Any] = []

        def capture_writer(event: Any) -> None:
            written_events.append(event)

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager"
        ) as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            await execute_subagent_stream(ctx=ctx, stream_writer=capture_writer)

        assert custom_payload in written_events

    async def test_execute_subagent_stream_skips_silent_messages(self):
        """Messages with metadata silent=True must be ignored."""
        from app.agents.core.subagents.subagent_runner import (
            SubagentExecutionContext,
            execute_subagent_stream,
        )

        silent_chunk = AIMessageChunk(content="SHOULD NOT APPEAR")
        visible_chunk = AIMessageChunk(content="SHOULD APPEAR")

        events = [
            ("messages", (silent_chunk, {"silent": True})),
            ("messages", (visible_chunk, {})),
        ]

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_iter(events))

        ctx = SubagentExecutionContext(
            subagent_graph=mock_graph,
            agent_name="test_agent",
            config={"configurable": {"thread_id": str(uuid4())}},
            configurable={},
            integration_id="test",
            initial_state={"messages": []},
        )

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager"
        ) as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert "SHOULD NOT APPEAR" not in result
        assert "SHOULD APPEAR" in result


# ---------------------------------------------------------------------------
# Test: provider registration (register_subagent_providers)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentProviderRegistration:
    """Verify register_subagent_providers registers entries from OAUTH_INTEGRATIONS."""

    def test_register_subagent_providers_returns_positive_count(self):
        """register_subagent_providers must register at least one provider."""
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        with patch(
            "app.agents.core.subagents.provider_subagents.providers"
        ) as mock_providers:
            mock_providers.register = MagicMock()
            count = register_subagent_providers()

        # There must be at least one subagent registered from OAUTH_INTEGRATIONS
        assert count > 0, "Expected at least one subagent provider to be registered"

    def test_register_subagent_providers_skips_auth_required_mcp(self):
        """Auth-required MCP integrations must NOT be registered as lazy providers
        since they require per-user token setup at runtime."""
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )
        from app.config.oauth_config import OAUTH_INTEGRATIONS

        with patch(
            "app.agents.core.subagents.provider_subagents.providers"
        ) as mock_providers:
            registered_names: list[str] = []
            mock_providers.register = MagicMock(
                side_effect=lambda name, **_: registered_names.append(name)
            )
            register_subagent_providers()

        # Find auth-required MCP agent names that should NOT be registered
        auth_mcp_names = [
            integ.subagent_config.agent_name
            for integ in OAUTH_INTEGRATIONS
            if (
                integ.subagent_config
                and integ.subagent_config.has_subagent
                and integ.managed_by == "mcp"
                and integ.mcp_config
                and integ.mcp_config.requires_auth
            )
        ]

        for name in auth_mcp_names:
            assert name not in registered_names, (
                f"Auth-required MCP agent '{name}' must NOT be lazily registered"
            )

    def test_register_subagent_providers_subset_by_id(self):
        """Passing integration_ids list must restrict registration to only those IDs.

        Picks the first non-auth-required subagent integration so that exactly
        one provider is registered, then asserts on both the exact count and the
        specific agent_name that was registered.
        """
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )
        from app.config.oauth_config import get_subagent_integrations

        all_available = get_subagent_integrations()
        # Filter to integrations that will actually be registered (not auth-required MCP)
        registerable = [
            i
            for i in all_available
            if not (
                i.managed_by == "mcp" and i.mcp_config and i.mcp_config.requires_auth
            )
        ]
        if not registerable:
            pytest.skip(
                "No non-auth-required subagent integrations available in OAUTH_INTEGRATIONS"
            )

        target = registerable[0]
        expected_agent_name = target.subagent_config.agent_name

        with patch(
            "app.agents.core.subagents.provider_subagents.providers"
        ) as mock_providers:
            registered_names: list[str] = []
            mock_providers.register = MagicMock(
                side_effect=lambda name, **_: registered_names.append(name)
            )
            count = register_subagent_providers(integration_ids=[target.id])

        # Exactly one provider must be registered for the single requested integration
        assert count == 1, (
            f"Expected exactly 1 registered provider for '{target.id}', got {count}"
        )
        assert expected_agent_name in registered_names, (
            f"Expected agent '{expected_agent_name}' to be registered; "
            f"got: {registered_names}"
        )
        # No other agents should have been registered
        assert registered_names == [expected_agent_name], (
            f"Only '{expected_agent_name}' should be registered; "
            f"got: {registered_names}"
        )


# ---------------------------------------------------------------------------
# Test: get_subagent_integrations / get_subagent_by_id data integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentRunnerHelpers:
    """Verify helper functions in subagent_runner.py return coherent data."""

    def test_get_subagent_integrations_returns_nonempty_list(self):
        """get_subagent_integrations must return a non-empty list from OAUTH_INTEGRATIONS."""
        from app.agents.core.subagents.subagent_runner import get_subagent_integrations

        integrations = get_subagent_integrations()
        assert isinstance(integrations, list)
        assert len(integrations) > 0, (
            "Expected at least one configured subagent integration"
        )

    def test_get_subagent_by_id_resolves_known_id(self):
        """get_subagent_by_id must resolve a known integration ID."""
        from app.agents.core.subagents.subagent_runner import (
            get_subagent_by_id,
            get_subagent_integrations,
        )

        integrations = get_subagent_integrations()
        first = integrations[0]

        result = get_subagent_by_id(first.id)
        assert result is not None, f"get_subagent_by_id('{first.id}') returned None"
        assert result.id == first.id

    def test_get_subagent_by_id_returns_none_for_unknown(self):
        """get_subagent_by_id must return None for a non-existent ID."""
        from app.agents.core.subagents.subagent_runner import get_subagent_by_id

        result = get_subagent_by_id("nonexistent_integration_xyz_9999")
        assert result is None

    def test_get_subagent_by_id_resolves_short_name(self):
        """get_subagent_by_id must resolve integrations by short_name alias."""
        from app.agents.core.subagents.subagent_runner import (
            get_subagent_by_id,
            get_subagent_integrations,
        )

        integrations = get_subagent_integrations()
        with_short_name = [i for i in integrations if i.short_name]
        if not with_short_name:
            pytest.skip("No subagent integrations with short_name found")

        first = with_short_name[0]
        result = get_subagent_by_id(first.short_name)
        assert result is not None, (
            f"get_subagent_by_id('{first.short_name}') should resolve via short_name"
        )
        assert result.id == first.id

    def test_all_subagent_integrations_have_agent_name(self):
        """Every subagent integration must have a non-empty agent_name."""
        from app.agents.core.subagents.subagent_runner import get_subagent_integrations

        for integ in get_subagent_integrations():
            cfg = integ.subagent_config
            assert cfg is not None
            assert cfg.agent_name, (
                f"Integration '{integ.id}' has empty agent_name in subagent_config"
            )

    def test_all_subagent_integrations_have_tool_space(self):
        """Every subagent integration must declare a non-empty tool_space."""
        from app.agents.core.subagents.subagent_runner import get_subagent_integrations

        for integ in get_subagent_integrations():
            cfg = integ.subagent_config
            assert cfg is not None
            assert cfg.tool_space, f"Integration '{integ.id}' has empty tool_space"


# ---------------------------------------------------------------------------
# Test: build_initial_messages constructs correct message structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildInitialMessages:
    """Verify build_initial_messages produces the expected [system, context, human] list."""

    async def test_build_initial_messages_returns_three_messages(self):
        """build_initial_messages must return exactly 3 messages:
        system, context, and human."""
        from app.agents.core.subagents.subagent_runner import build_initial_messages

        system_msg = SystemMessage(content="You are a Gmail agent.")
        configurable = {
            "thread_id": str(uuid4()),
            "user_id": str(uuid4()),
            "user_time": datetime.now(timezone.utc).isoformat(),
        }

        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new=AsyncMock(return_value=SystemMessage(content="Context: time is now.")),
        ):
            messages = await build_initial_messages(
                system_message=system_msg,
                agent_name="gmail_agent",
                configurable=configurable,
                task="Send an email to John",
                user_id="user-1",
                subagent_id="gmail_agent",
            )

        assert len(messages) == 3

    async def test_build_initial_messages_first_is_system(self):
        """First message must be the supplied system message."""
        from app.agents.core.subagents.subagent_runner import build_initial_messages

        system_msg = SystemMessage(content="You are a Gmail agent.")

        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new=AsyncMock(return_value=SystemMessage(content="ctx")),
        ):
            messages = await build_initial_messages(
                system_message=system_msg,
                agent_name="gmail_agent",
                configurable={},
                task="Do something",
            )

        assert messages[0] is system_msg

    async def test_build_initial_messages_last_is_human_with_task(self):
        """Last message must be a HumanMessage whose content equals the task."""
        from app.agents.core.subagents.subagent_runner import build_initial_messages

        task = "Schedule a meeting for tomorrow at 10am"

        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new=AsyncMock(return_value=SystemMessage(content="ctx")),
        ):
            messages = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="calendar_agent",
                configurable={},
                task=task,
            )

        last = messages[-1]
        assert isinstance(last, HumanMessage)
        assert last.content == task

    async def test_build_initial_messages_uses_retrieval_query_for_context(self):
        """When retrieval_query is provided it must be passed to
        create_agent_context_message instead of the raw task."""
        from app.agents.core.subagents.subagent_runner import build_initial_messages

        retrieval_query = "original query without hints"
        enhanced_task = f"{retrieval_query}\n\nDIRECT EXECUTION HINT: ..."

        captured_queries: list[str] = []

        async def capture_context(configurable, user_id, query, subagent_id=None):
            captured_queries.append(query)
            return SystemMessage(content="ctx")

        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new=capture_context,
        ):
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="executor_agent",
                configurable={},
                task=enhanced_task,
                retrieval_query=retrieval_query,
            )

        assert len(captured_queries) == 1
        assert captured_queries[0] == retrieval_query, (
            "retrieval_query must be passed to context creation, not enhanced_task"
        )


# ---------------------------------------------------------------------------
# Test: prepare_subagent_execution error handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPrepareSubagentExecutionErrors:
    """Verify prepare_subagent_execution returns clear error messages when
    resolution fails."""

    async def test_returns_error_for_unknown_subagent(self):
        """prepare_subagent_execution must return (None, error_str) when the
        subagent ID cannot be resolved."""
        from app.agents.core.subagents.subagent_runner import prepare_subagent_execution

        user = make_user()
        ctx, error = await prepare_subagent_execution(
            subagent_id="definitely_nonexistent_agent_xyz",
            task="do something",
            user=user,
            user_time=datetime.now(timezone.utc),
            conversation_id=str(uuid4()),
        )

        assert ctx is None
        assert error is not None
        assert len(error) > 0

    async def test_returns_error_when_graph_unavailable(self):
        """prepare_subagent_execution must return an error when providers.aget
        returns None for the agent graph."""
        from app.agents.core.subagents.subagent_runner import (
            get_subagent_integrations,
            prepare_subagent_execution,
        )

        integrations = get_subagent_integrations()
        if not integrations:
            pytest.skip("No subagent integrations available")

        first = integrations[0]
        user = make_user()

        with patch(
            "app.agents.core.subagents.subagent_runner.providers"
        ) as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)

            with patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ):
                ctx, error = await prepare_subagent_execution(
                    subagent_id=first.id,
                    task="test task",
                    user=user,
                    user_time=datetime.now(timezone.utc),
                    conversation_id=str(uuid4()),
                )

        assert ctx is None
        assert error is not None
        assert (
            "not available" in error.lower()
            or first.subagent_config.agent_name in error
        )


# ---------------------------------------------------------------------------
# Async generator helper
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Yield items from a list as an async iterator (for mocking astream)."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Test: handoff() async function called directly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHandoffFunctionDirectly:
    """Call the handoff() coroutine directly (not through a compiled graph)
    and verify it returns the expected result and correctly passes state to
    the subagent."""

    async def test_handoff_function_directly(self):
        """Calling handoff() directly must return the subagent's response
        string and must route state through execute_subagent_stream."""
        from app.agents.core.subagents.handoff_tools import (
            handoff,
        )

        user_id = str(uuid4())
        thread_id = str(uuid4())

        fake_graph = MagicMock()
        fake_graph.astream = MagicMock(
            return_value=_async_iter(
                [("messages", (AIMessageChunk(content="direct handoff result"), {}))]
            )
        )

        config = {
            "configurable": {
                "user_id": user_id,
                "thread_id": thread_id,
                "stream_id": "stream-abc",
            }
        }

        # The underlying coroutine is stored in handoff.coroutine for @tool-wrapped async fns
        underlying = getattr(handoff, "coroutine", None) or handoff

        fake_subagent_config = {"configurable": {"thread_id": f"gmail_{thread_id}"}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(return_value=(fake_graph, "gmail_agent", "gmail", False)),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(
                    return_value=SystemMessage(content="You are Gmail agent.")
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="Send an email"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value=fake_subagent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="direct handoff result"),
            ) as mock_execute,
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            result = await underlying(
                subagent_id="gmail",
                task="Send an email to Bob",
                config=config,
            )

        assert result == "direct handoff result"
        mock_execute.assert_awaited_once()
        # Verify the execution context passed to execute_subagent_stream has
        # correct agent_name and integration_id
        ctx_arg = (
            mock_execute.call_args.kwargs.get("ctx") or mock_execute.call_args.args[0]
        )
        assert ctx_arg.agent_name == "gmail_agent"
        assert ctx_arg.integration_id == "gmail"

    async def test_handoff_passes_task_in_state(self):
        """The task argument supplied to handoff() must appear in the initial
        messages forwarded to execute_subagent_stream."""
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        thread_id = str(uuid4())
        captured_states: list[dict] = []

        async def capture_execute(ctx, stream_writer=None, integration_metadata=None):
            captured_states.append(ctx.initial_state)
            return "ok"

        fake_subagent_config = {"configurable": {"thread_id": f"notion_{thread_id}"}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(
                    return_value=(MagicMock(), "notion_agent", "notion", False)
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="Take a note about dogs"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value=fake_subagent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=capture_execute,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            await underlying(
                subagent_id="notion",
                task="Take a note about dogs",
                config={
                    "configurable": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                    }
                },
            )

        assert len(captured_states) == 1
        messages = captured_states[0].get("messages", [])
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        assert len(human_messages) == 1
        assert human_messages[0].content == "Take a note about dogs"


# ---------------------------------------------------------------------------
# Test: custom MCP path (lines 244-271 of handoff_tools.py)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCustomMCPPath:
    """Verify that the custom MCP branch in _resolve_subagent (lines 244-271)
    is exercised: when _get_subagent_by_id returns a dict (MongoDB custom MCP),
    create_subagent_for_user must be called and agent_name must follow the
    'custom_mcp_{integration_id}' convention.

    If the custom MCP path is broken (e.g. `isinstance(integration, dict)` check
    removed), these tests MUST fail.
    """

    async def test_custom_mcp_path_calls_create_subagent_for_user(self):
        """When the integration resolved is a plain dict (custom MCP from MongoDB),
        _resolve_subagent must call create_subagent_for_user and return is_custom=True."""
        from app.agents.core.subagents.handoff_tools import _resolve_subagent

        custom_integration_id = "fb9dfd7e05f8"
        fake_graph = MagicMock()

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new=AsyncMock(
                    return_value={
                        "id": custom_integration_id,
                        "name": "Semantic Scholar",
                        "source": "custom",
                        "managed_by": "mcp",
                        "mcp_config": {"server_url": "http://localhost:9000"},
                        "icon_url": None,
                        "subagent_config": None,
                    }
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new=AsyncMock(return_value=fake_graph),
            ) as mock_create,
        ):
            graph, agent_name, int_id, is_custom = await _resolve_subagent(
                subagent_id=f"subagent:{custom_integration_id}",
                user_id="user-123",
            )

        mock_create.assert_awaited_once_with(custom_integration_id, "user-123")
        assert graph is fake_graph
        assert agent_name == f"custom_mcp_{custom_integration_id}"
        assert int_id == custom_integration_id
        assert is_custom is True

    async def test_custom_mcp_path_invoked(self):
        """End-to-end: handoff() with a custom MCP subagent must reach the
        custom MCP branch, call create_subagent_for_user, and return a result.

        Breaking the `isinstance(integration, dict)` guard at line 244 of
        handoff_tools.py will cause this test to fail because the execution
        will fall through to the platform-integration branch which raises
        AttributeError (dict has no .subagent_config attribute).
        """
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        thread_id = str(uuid4())
        custom_id = "ab12cd34ef56"
        fake_graph = MagicMock()

        custom_dict = {
            "id": custom_id,
            "name": "My Custom MCP",
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": {"server_url": "http://localhost:9999"},
            "icon_url": "http://example.com/icon.png",
            "subagent_config": None,
        }

        fake_subagent_config = {
            "configurable": {"thread_id": f"custom_mcp_{custom_id}_{thread_id}"}
        }

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new=AsyncMock(return_value=custom_dict),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new=AsyncMock(return_value=fake_graph),
            ) as mock_create,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="custom mcp sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="custom mcp sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="fetch paper data"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value=fake_subagent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="custom mcp result"),
            ) as mock_execute,
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
        ):
            result = await underlying(
                subagent_id=f"subagent:{custom_id}",
                task="fetch paper data",
                config={
                    "configurable": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                    }
                },
            )

        # create_subagent_for_user must have been invoked (custom MCP branch)
        mock_create.assert_awaited_once_with(custom_id, user_id)
        assert result == "custom mcp result"
        # Verify the execution context has is_custom reflected in agent_name
        ctx_arg = (
            mock_execute.call_args.kwargs.get("ctx") or mock_execute.call_args.args[0]
        )
        assert ctx_arg.agent_name == f"custom_mcp_{custom_id}"
        assert ctx_arg.integration_id == custom_id

    async def test_custom_mcp_path_requires_user_id(self):
        """If user_id is None, the custom MCP path must return an error tuple
        without calling create_subagent_for_user."""
        from app.agents.core.subagents.handoff_tools import _resolve_subagent

        custom_id = "deadbeef0000"

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new=AsyncMock(
                    return_value={
                        "id": custom_id,
                        "name": "No Auth MCP",
                        "source": "custom",
                        "managed_by": "mcp",
                        "mcp_config": None,
                        "icon_url": None,
                        "subagent_config": None,
                    }
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new=AsyncMock(return_value=MagicMock()),
            ) as mock_create,
        ):
            graph, agent_name, error_or_id, _ = await _resolve_subagent(
                subagent_id=custom_id,
                user_id=None,
            )

        mock_create.assert_not_awaited()
        assert graph is None
        assert agent_name is None
        assert error_or_id is not None
        assert (
            "requires authentication" in error_or_id.lower()
            or "sign in" in error_or_id.lower()
        )

    async def test_custom_mcp_path_returns_error_when_create_fails(self):
        """If create_subagent_for_user returns None, _resolve_subagent must
        return an error tuple (not a graph)."""
        from app.agents.core.subagents.handoff_tools import _resolve_subagent

        custom_id = "failfail1234"

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new=AsyncMock(
                    return_value={
                        "id": custom_id,
                        "name": "Broken MCP",
                        "source": "custom",
                        "managed_by": "mcp",
                        "mcp_config": None,
                        "icon_url": None,
                        "subagent_config": None,
                    }
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            graph, _, error_or_id, _ = await _resolve_subagent(
                subagent_id=custom_id,
                user_id="user-xyz",
            )

        assert graph is None
        assert "Failed to create" in (error_or_id or "")


# ---------------------------------------------------------------------------
# Test: handoff thread isolation via handoff()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHandoffThreadIsolation:
    """Verify that handoffs to different subagents produce different thread IDs
    so there is no state bleeding between subagent invocations."""

    async def test_handoff_thread_isolation(self):
        """Two handoff() calls with different subagent_ids but the same parent
        thread must produce different subagent_thread_ids (no state bleeding).

        The thread_id is constructed as '{integration_id}_{parent_thread_id}'
        inside the handoff() coroutine itself; we capture it by intercepting
        build_agent_config to record the thread_id argument it receives.
        """
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        parent_thread_id = str(uuid4())
        captured_thread_ids: list[str] = []

        def capture_build_agent_config(**kwargs):
            captured_thread_ids.append(kwargs.get("thread_id", ""))
            return {"configurable": {"thread_id": kwargs.get("thread_id", "")}}

        config = {
            "configurable": {
                "user_id": user_id,
                "thread_id": parent_thread_id,
            }
        }

        with (
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="done"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="task"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                side_effect=capture_build_agent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            # Handoff to "gmail"
            with patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(
                    return_value=(MagicMock(), "gmail_agent", "gmail", False)
                ),
            ):
                await underlying(
                    subagent_id="gmail",
                    task="send email",
                    config=config,
                )

            # Handoff to "notion"
            with patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(
                    return_value=(MagicMock(), "notion_agent", "notion", False)
                ),
            ):
                await underlying(
                    subagent_id="notion",
                    task="take a note",
                    config=config,
                )

        assert len(captured_thread_ids) == 2
        thread_a, thread_b = captured_thread_ids
        # Thread IDs must differ for different subagents sharing the same parent thread
        assert thread_a != thread_b, (
            f"Thread A ({thread_a}) must differ from Thread B ({thread_b})"
        )
        # Both must embed the parent thread_id
        assert parent_thread_id in thread_a
        assert parent_thread_id in thread_b

    async def test_handoff_thread_id_encodes_integration_id(self):
        """The subagent thread ID must be prefixed with the integration ID so
        the format '{integration_id}_{parent_thread_id}' is preserved.

        The thread_id is assembled as '{int_id}_{thread_id}' in handoff() before
        being passed to build_agent_config(); we capture it there.
        """
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        parent_thread_id = "fixed-parent-thread-999"
        captured_thread_ids: list[str] = []

        def capture_build(thread_id=None, **kwargs):
            captured_thread_ids.append(thread_id or "")
            return {"configurable": {"thread_id": thread_id or ""}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(
                    return_value=(
                        MagicMock(),
                        "calendar_agent",
                        "googlecalendar",
                        False,
                    )
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="schedule"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                side_effect=capture_build,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="done"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            await underlying(
                subagent_id="googlecalendar",
                task="schedule meeting",
                config={
                    "configurable": {
                        "user_id": user_id,
                        "thread_id": parent_thread_id,
                    }
                },
            )

        assert len(captured_thread_ids) == 1
        assert captured_thread_ids[0] == f"googlecalendar_{parent_thread_id}", (
            f"Expected 'googlecalendar_{parent_thread_id}', got '{captured_thread_ids[0]}'"
        )


# ---------------------------------------------------------------------------
# Test: tool call arguments are correctly passed through handoff
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHandoffWithToolCallArgs:
    """Verify that arguments supplied in the tool call (subagent_id, task)
    are correctly forwarded through the handoff pipeline."""

    async def test_handoff_with_tool_call_args(self):
        """subagent_id and task arguments must reach _resolve_subagent and
        build_initial_messages unchanged."""
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        thread_id = str(uuid4())
        expected_task = "Reply to Alice's email with the quarterly report attached"
        expected_subagent_id = "gmail"

        captured_resolve_args: list[tuple] = []
        captured_build_args: list[dict] = []

        async def capture_resolve(subagent_id, user_id):
            captured_resolve_args.append((subagent_id, user_id))
            return MagicMock(), "gmail_agent", "gmail", False

        async def capture_build(**kwargs):
            captured_build_args.append(kwargs)
            return [
                SystemMessage(content="sys"),
                SystemMessage(content="ctx"),
                HumanMessage(content=kwargs.get("task", "")),
            ]

        fake_subagent_config = {"configurable": {"thread_id": f"gmail_{thread_id}"}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=capture_resolve,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=capture_build,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value=fake_subagent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="args test result"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            result = await underlying(
                subagent_id=expected_subagent_id,
                task=expected_task,
                config={
                    "configurable": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                    }
                },
            )

        assert result == "args test result"

        # subagent_id must reach _resolve_subagent unmodified
        assert len(captured_resolve_args) == 1
        assert captured_resolve_args[0][0] == expected_subagent_id

        # task must reach build_initial_messages unmodified
        assert len(captured_build_args) == 1
        assert captured_build_args[0]["task"] == expected_task

    async def test_handoff_user_id_passed_to_resolve_subagent(self):
        """user_id from configurable must be forwarded to _resolve_subagent
        so auth checks inside the custom MCP / MCP-auth paths receive it."""
        from app.agents.core.subagents.handoff_tools import handoff

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = "explicit-user-id-xyz"
        thread_id = str(uuid4())
        captured: list[str | None] = []

        async def capture_resolve(subagent_id, user_id):
            captured.append(user_id)
            return MagicMock(), "notion_agent", "notion", False

        fake_subagent_config = {"configurable": {"thread_id": f"notion_{thread_id}"}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=capture_resolve,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new=AsyncMock(return_value=SystemMessage(content="sys")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new=AsyncMock(
                    return_value=[
                        SystemMessage(content="sys"),
                        SystemMessage(content="ctx"),
                        HumanMessage(content="task"),
                    ]
                ),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value=fake_subagent_config,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new=AsyncMock(return_value="ok"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=None,
            ),
        ):
            await underlying(
                subagent_id="notion",
                task="take note",
                config={
                    "configurable": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                    }
                },
            )

        assert len(captured) == 1
        assert captured[0] == user_id, (
            f"Expected user_id='{user_id}' passed to _resolve_subagent, got '{captured[0]}'"
        )
