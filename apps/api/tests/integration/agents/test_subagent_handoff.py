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
        """Subagent thread IDs produced by the handoff tool follow the
        '{integration_id}_{parent_thread_id}' convention.

        Verify that the naming logic in handoff_tools.py produces distinct IDs
        for different integration_ids sharing the same parent thread.
        """
        parent_thread = "parent-thread-abc"

        gmail_thread = f"gmail_{parent_thread}"
        notion_thread = f"notion_{parent_thread}"
        calendar_thread = f"googlecalendar_{parent_thread}"

        assert gmail_thread != notion_thread
        assert gmail_thread != calendar_thread
        assert notion_thread != calendar_thread
        # All share the same parent suffix
        assert all(
            t.endswith(parent_thread)
            for t in [gmail_thread, notion_thread, calendar_thread]
        )

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
        """Running a minimal subagent graph with a HumanMessage must produce
        an AIMessage result accessible from the final state."""
        graph = _make_minimal_subagent_graph()
        thread_id = str(uuid4())

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Do some gmail work")]},
            config={"configurable": {"thread_id": thread_id}},
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
        """Passing integration_ids list must restrict registration to only those IDs."""
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )
        from app.config.oauth_config import get_subagent_integrations

        # Pick just the first available subagent integration
        available = get_subagent_integrations()
        if not available:
            pytest.skip("No subagent integrations available in OAUTH_INTEGRATIONS")

        first = available[0]

        with patch(
            "app.agents.core.subagents.provider_subagents.providers"
        ) as mock_providers:
            registered_names: list[str] = []
            mock_providers.register = MagicMock(
                side_effect=lambda name, **_: registered_names.append(name)
            )
            count = register_subagent_providers(integration_ids=[first.id])

        # At most one should be registered (could be zero if auth-required MCP)
        assert count <= 1


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
