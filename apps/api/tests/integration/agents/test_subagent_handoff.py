"""Integration tests for subagent handoff chain.

Covers the comms -> executor -> subagent delegation path:
- SubAgentFactory.create_provider_subagent can be instantiated
- handoff tool has the correct schema / is importable from production code
- SubagentExecutionContext stores all fields correctly
- Different thread IDs produce independent checkpointed state
- build_initial_messages constructs the correct 3-message list
- get_subagent_by_id / all_subagents return real data
- register_subagent_providers registers integrations from the subagent registry
- execute_subagent_stream processes streamed events correctly

All external I/O (LLM, DB, Composio, Redis, MCP servers) is mocked.
Real production classes and functions are imported so tests fail if code moves.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, interrupt
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import PromptSlot, slot_of
from app.agents.context.tiers import AgentTier
from app.agents.core.subagents.base_subagent import SubAgentFactory
from app.agents.core.subagents.handoff_tools import (
    _resolve_subagent,
    handoff,
    resume_parked_subagent,
)
from app.agents.core.subagents.provider_subagents import SubagentUnavailableError
from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
    build_initial_messages,
    execute_subagent_stream,
    interrupt_payload,
)
from app.constants.hil import HIL_RESUME_CONFIG_KEY, LANGGRAPH_INTERRUPT_KEY
from app.models.hil_models import HILApprovalRecord
from tests.helpers import create_fake_llm

HANDOFF_MODULE = "app.agents.core.subagents.handoff_tools"
BASE_SUBAGENT_MODULE = "app.agents.core.subagents.base_subagent"

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


# ---------------------------------------------------------------------------
# Test: SubAgentFactory is importable and its static method is callable
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubAgentCanBeInstantiated:
    """Verify SubAgentFactory can be imported and its factory method invoked
    with mocked infrastructure."""

    def test_subagent_factory_class_is_importable(self):
        """Importing SubAgentFactory must not raise; the class must exist."""

        assert SubAgentFactory is not None

    def test_create_provider_subagent_method_exists(self):
        """SubAgentFactory.create_provider_subagent must be a static async method."""

        method = getattr(SubAgentFactory, "create_provider_subagent", None)
        assert method is not None, "create_provider_subagent not found on SubAgentFactory"
        assert callable(method)

    async def test_create_provider_subagent_compiles_graph(self):
        """SubAgentFactory.create_provider_subagent must yield a compiled graph
        when all external calls are mocked."""

        fake_llm = create_fake_llm(["subagent answer"])
        mock_store = _make_mock_store()
        mock_registry = _make_mock_tool_registry()

        with (
            # get_tool_registry is imported at module top in base_subagent, so it
            # must be patched on base_subagent (where the name is bound), not at its
            # source module. deep_research / web_search_tool / fetch_webpages are
            # only inserted into the tool dict (never invoked here), so patching them
            # at their source modules is sufficient.
            patch(
                "app.agents.core.subagents.base_subagent.get_tool_registry",
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

        assert handoff is not None

    def test_handoff_tool_name(self):
        """handoff.name must be 'handoff'."""

        assert handoff.name == "handoff"

    def test_handoff_tool_schema_contains_required_params(self):
        """handoff schema must expose subagent_id and task as required inputs."""

        schema = handoff.args_schema.schema() if handoff.args_schema else {}
        # args_schema may not be set; fall back to tool.schema()
        if not schema:
            schema = handoff.schema() if hasattr(handoff, "schema") else {}

        # The tool is annotated with subagent_id and task parameters.
        # For async @tool-decorated functions LangChain stores the original coroutine
        # in `.coroutine`; `.func` is used for sync tools.
        import inspect

        underlying = (
            getattr(handoff, "coroutine", None) or getattr(handoff, "func", None) or handoff
        )
        sig = inspect.signature(underlying)
        param_names = set(sig.parameters.keys())

        assert "subagent_id" in param_names, (
            f"handoff must accept 'subagent_id'; found params: {param_names}"
        )
        assert "task" in param_names, f"handoff must accept 'task'; found params: {param_names}"

    def test_handoff_tool_is_async(self):
        """handoff must be an async function (coroutine function)."""
        import inspect

        # For async @tool-decorated functions LangChain stores the original coroutine
        # in `.coroutine`; `.func` is used for sync tools.
        underlying = (
            getattr(handoff, "coroutine", None) or getattr(handoff, "func", None) or handoff
        )
        assert inspect.iscoroutinefunction(underlying), "handoff tool must be async"

    def test_handoff_tool_has_docstring(self):
        """handoff must have a non-empty description for the LLM."""

        description = handoff.description
        assert description and len(description) > 10, "handoff tool description must be informative"


# ---------------------------------------------------------------------------
# Test: SubagentExecutionContext stores fields correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentExecutionContext:
    """Verify SubagentExecutionContext is importable and stores all fields."""

    def test_context_is_importable(self):
        """SubagentExecutionContext must be importable from subagent_runner."""
        from app.agents.core.subagents.subagent_runner import (
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
        with patch("app.agents.core.subagents.subagent_runner.stream_manager") as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        # The production function read ctx.initial_state, ctx.config, ctx.stream_id
        # correctly — if any field name were wrong the call would have raised
        assert not result.paused
        assert "context field test passed" in result.text
        mock_graph.astream.assert_called_once_with(
            ctx.initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=ctx.config,
            # The executor/subagent path now persists checkpoints only on exit,
            # not after every step, to cut Postgres checkpoint churn.
            durability="exit",
        )


# ---------------------------------------------------------------------------
# Test: thread ID isolation
# ---------------------------------------------------------------------------


@pytest.fixture
async def real_subagent_seams():
    """Build ONE real compiled subagent graph via SubAgentFactory (production
    code, not a graph built from scratch in the test), shared across both
    handoff() calls — isolation must come from handoff()'s own thread_id
    derivation and the real checkpointer, not from using separate graph
    objects per thread."""
    fake_llm = create_fake_llm(["ack"])
    mock_store = _make_mock_store()
    mock_registry = _make_mock_tool_registry()
    saver = InMemorySaver()

    with (
        patch(f"{BASE_SUBAGENT_MODULE}.get_tool_registry", AsyncMock(return_value=mock_registry)),
        patch(f"{BASE_SUBAGENT_MODULE}.get_tools_store", AsyncMock(return_value=mock_store)),
        patch(
            f"{BASE_SUBAGENT_MODULE}.get_checkpointer_manager",
            AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: saver)),
        ),
        patch(f"{BASE_SUBAGENT_MODULE}.create_subagent_middleware", return_value=[]),
        patch(f"{BASE_SUBAGENT_MODULE}.create_todo_tools", return_value=[]),
        patch(f"{BASE_SUBAGENT_MODULE}.create_todo_pre_model_hook", return_value=None),
    ):
        graph = await SubAgentFactory.create_provider_subagent(
            provider="gmail",
            name="gmail_agent",
            llm=fake_llm,
            tool_space="gmail_delegated",
            use_direct_tools=True,
            disable_retrieve_tools=True,
        )

    with (
        patch(
            f"{HANDOFF_MODULE}._resolve_subagent",
            AsyncMock(return_value=(graph, "gmail_agent", "gmail", False)),
        ),
        patch(
            f"{HANDOFF_MODULE}.create_subagent_system_message",
            AsyncMock(return_value=SystemMessage(content="You are the Gmail agent.")),
        ),
        patch(f"{HANDOFF_MODULE}.get_provider_metadata", AsyncMock(return_value=None)),
        patch(
            f"{HANDOFF_MODULE}.list_parked_subagents_for_conversation",
            AsyncMock(return_value=[]),
        ),
        # handoff() is invoked directly here (no parent graph node), so there is
        # no active LangGraph runnable context for get_stream_writer() to hook.
        patch(f"{HANDOFF_MODULE}.get_stream_writer", return_value=MagicMock()),
        patch(
            "app.agents.core.subagents.subagent_runner.assemble_context",
            AsyncMock(
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                )
            ),
        ),
        patch(
            "app.utils.agent_utils.get_tool_registry",
            AsyncMock(return_value=SimpleNamespace(get_category_of_tool=lambda _name: "general")),
        ),
    ):
        yield graph


@pytest.mark.integration
class TestSubagentThreadIsolation:
    """A handoff to the SAME subagent from two different parent conversations
    must not leak state between them. Drives the real handoff() tool and a
    real SubAgentFactory-built graph — proving GAIA's own thread-id derivation
    and checkpointer isolate state, not just LangGraph's MemorySaver in a toy
    graph built from scratch for the test."""

    async def test_handoff_from_different_parent_threads_is_isolated(
        self, real_subagent_seams
    ) -> None:
        graph = real_subagent_seams
        parent_a = str(uuid4())
        parent_b = str(uuid4())

        result_a = await handoff.coroutine(
            subagent_id="gmail",
            task="Summarize thread Alpha",
            config={"configurable": {"user_id": "user-iso-1", "thread_id": parent_a}},
        )
        result_b = await handoff.coroutine(
            subagent_id="gmail",
            task="Summarize thread Bravo",
            config={"configurable": {"user_id": "user-iso-1", "thread_id": parent_b}},
        )

        assert result_a
        assert result_b

        # Real format from handoff_tools.py: f"{integration_id}_{parent_thread_id}"
        thread_id_a = f"gmail_{parent_a}"
        thread_id_b = f"gmail_{parent_b}"
        assert thread_id_a != thread_id_b

        state_a = await graph.aget_state({"configurable": {"thread_id": thread_id_a}})
        state_b = await graph.aget_state({"configurable": {"thread_id": thread_id_b}})

        content_a = " ".join(
            m.content for m in state_a.values["messages"] if isinstance(m, HumanMessage)
        )
        content_b = " ".join(
            m.content for m in state_b.values["messages"] if isinstance(m, HumanMessage)
        )

        assert "Summarize thread Alpha" in content_a
        assert "Summarize thread Bravo" not in content_a, (
            "thread A's checkpointed state must not contain thread B's task"
        )
        assert "Summarize thread Bravo" in content_b
        assert "Summarize thread Alpha" not in content_b, (
            "thread B's checkpointed state must not contain thread A's task"
        )


# ---------------------------------------------------------------------------
# Test: subagent graph run with mocked external calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentRun:
    """Run a subagent through its graph with all external calls mocked."""

    async def test_execute_subagent_stream_returns_content(self):
        """execute_subagent_stream must accumulate AI content from messages
        stream events and return the joined string."""
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

        with patch("app.agents.core.subagents.subagent_runner.stream_manager") as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert not result.paused
        assert "Hello from Gmail agent" in result.text

    async def test_execute_subagent_stream_default_on_empty(self):
        """execute_subagent_stream must return 'Task completed' when no AI
        content is produced."""
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

        with patch("app.agents.core.subagents.subagent_runner.stream_manager") as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert not result.paused
        assert result.text == "Task completed"

    async def test_execute_subagent_stream_forwards_custom_events(self):
        """Custom stream events must be forwarded to the stream_writer."""
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

        with patch("app.agents.core.subagents.subagent_runner.stream_manager") as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            await execute_subagent_stream(ctx=ctx, stream_writer=capture_writer)

        assert custom_payload in written_events

    async def test_execute_subagent_stream_skips_silent_messages(self):
        """Messages with metadata silent=True must be ignored."""
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

        with patch("app.agents.core.subagents.subagent_runner.stream_manager") as mock_sm:
            mock_sm.is_cancelled = AsyncMock(return_value=False)
            result = await execute_subagent_stream(ctx=ctx, stream_writer=None)

        assert "SHOULD NOT APPEAR" not in result.text
        assert "SHOULD APPEAR" in result.text


# ---------------------------------------------------------------------------
# Test: provider registration (register_subagent_providers)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentProviderRegistration:
    """Verify register_subagent_providers registers entries from the subagent registry."""

    def test_register_subagent_providers_returns_positive_count(self):
        """register_subagent_providers must register at least one provider."""
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        with patch("app.agents.core.subagents.provider_subagents.providers") as mock_providers:
            mock_providers.register = MagicMock()
            count = register_subagent_providers()

        # There must be at least one subagent registered from the subagent registry
        assert count > 0, "Expected at least one subagent provider to be registered"

    def test_register_subagent_providers_skips_auth_required_mcp(self):
        """Auth-required MCP integrations must NOT be registered as lazy providers
        since they require per-user token setup at runtime."""
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        with patch("app.agents.core.subagents.provider_subagents.providers") as mock_providers:
            registered_names: list[str] = []
            mock_providers.register = MagicMock(
                side_effect=lambda name, **_: registered_names.append(name)
            )
            register_subagent_providers()

        # Find auth-required MCP agent names that should NOT be registered
        auth_mcp_names = [
            sa.config.agent_name
            for sa in all_subagents()
            if (sa.managed_by == "mcp" and sa.mcp_config and sa.mcp_config.requires_auth)
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

        all_available = all_subagents()
        # Filter to integrations that will actually be registered (not auth-required MCP)
        registerable = [
            i
            for i in all_available
            if not (i.managed_by == "mcp" and i.mcp_config and i.mcp_config.requires_auth)
        ]
        if not registerable:
            pytest.skip("No non-auth-required subagent integrations available in registry")

        target = registerable[0]
        expected_agent_name = target.config.agent_name

        with patch("app.agents.core.subagents.provider_subagents.providers") as mock_providers:
            registered_names: list[str] = []
            mock_providers.register = MagicMock(
                side_effect=lambda name, **_: registered_names.append(name)
            )
            count = register_subagent_providers(integration_ids=[target.id])

        # Exactly one provider must be registered for the single requested integration
        assert count == 1, f"Expected exactly 1 registered provider for '{target.id}', got {count}"
        assert expected_agent_name in registered_names, (
            f"Expected agent '{expected_agent_name}' to be registered; got: {registered_names}"
        )
        # No other agents should have been registered
        assert registered_names == [expected_agent_name], (
            f"Only '{expected_agent_name}' should be registered; got: {registered_names}"
        )


# ---------------------------------------------------------------------------
# Test: all_subagents / get_subagent_by_id data integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubagentRunnerHelpers:
    """Verify helper functions in subagent_runner.py return coherent data."""

    def test_all_subagents_returns_nonempty_list(self):
        """all_subagents must return a non-empty tuple from the registry."""
        integrations = all_subagents()
        assert isinstance(integrations, tuple)
        assert len(integrations) > 0, "Expected at least one configured subagent integration"

    def test_get_subagent_by_id_resolves_known_id(self):
        """get_subagent_by_id must resolve a known integration ID."""
        integrations = all_subagents()
        first = integrations[0]

        result = get_subagent_by_id(first.id)
        assert result is not None, f"get_subagent_by_id('{first.id}') returned None"
        assert result.id == first.id

    def test_get_subagent_by_id_returns_none_for_unknown(self):
        """get_subagent_by_id must return None for a non-existent ID."""
        result = get_subagent_by_id("nonexistent_integration_xyz_9999")
        assert result is None

    def test_get_subagent_by_id_resolves_short_name(self):
        """get_subagent_by_id must resolve integrations by short_name alias."""
        integrations = all_subagents()
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
        for sa in all_subagents():
            assert sa.config.agent_name, f"Integration '{sa.id}' has empty agent_name in config"

    def test_all_subagent_integrations_have_tool_space(self):
        """Every subagent integration must declare a non-empty tool_space."""
        for sa in all_subagents():
            assert sa.config.tool_space, f"Integration '{sa.id}' has empty tool_space"


# ---------------------------------------------------------------------------
# Test: build_initial_messages constructs correct message structure
# ---------------------------------------------------------------------------


def _assembled_context():
    """Stub the assembly step; these tests are about the seeder, not the sections."""
    return patch(
        "app.agents.core.subagents.subagent_runner.assemble_context",
        new_callable=AsyncMock,
        return_value=AssembledContext(
            stable=SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True}),
            volatile=None,
        ),
    )


@pytest.mark.integration
class TestBuildInitialMessages:
    """The seed a worker tier hands LangGraph, assembled through the real
    section registry rather than a stub — the unit tier already pins the shape,
    so what this adds is that the registry and the seeder agree in situ."""

    async def test_seed_is_in_canonical_slot_order(self) -> None:
        system_msg = SystemMessage(content="You are a Gmail agent.")

        with _assembled_context():
            messages = await build_initial_messages(
                system_message=system_msg,
                tier=AgentTier.PROVIDER_SUBAGENT,
                agent_name="gmail_agent",
                configurable={
                    "thread_id": str(uuid4()),
                    "user_id": str(uuid4()),
                    "user_timezone": "Asia/Kolkata",
                },
                task="Send an email to John",
                user_id="user-1",
                subagent_id="gmail_agent",
            )

        assert messages[0] is system_msg
        slots = [slot_of(m) for m in messages]
        assert slots == sorted(slots)
        assert slots[-1] is PromptSlot.TIME

    async def test_the_task_reaches_the_agent_as_a_human_turn(self) -> None:
        task = "Schedule a meeting for tomorrow at 10am"

        with _assembled_context():
            messages = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.PROVIDER_SUBAGENT,
                agent_name="calendar_agent",
                configurable={},
                task=task,
            )

        task_msgs = [
            m for m in messages if m.type == "human" and not m.additional_kwargs.get("time_context")
        ]
        assert [m.content for m in task_msgs] == [task]

    async def test_retrieval_query_is_what_the_sections_search_on(self) -> None:
        """The executor injects routing hints into the task text. Retrieving
        against those searches memory for our own words, not the user's."""
        retrieval_query = "original query without hints"
        enhanced_task = f"{retrieval_query}\n\nDIRECT EXECUTION HINT: ..."

        with _assembled_context() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.EXECUTOR,
                agent_name="executor_agent",
                configurable={},
                task=enhanced_task,
                retrieval_query=retrieval_query,
            )

        assert mock_assemble.call_args.args[0].query == retrieval_query


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
                new=AsyncMock(return_value=SystemMessage(content="You are Gmail agent.")),
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
                new=AsyncMock(return_value=SubagentOutcome(text="direct handoff result")),
            ) as mock_execute,
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
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
        ctx_arg = mock_execute.call_args.kwargs.get("ctx") or mock_execute.call_args.args[0]
        assert ctx_arg.agent_name == "gmail_agent"
        assert ctx_arg.integration_id == "gmail"

    async def test_handoff_passes_task_in_state(self):
        """The task argument supplied to handoff() must appear in the initial
        messages forwarded to execute_subagent_stream."""

        underlying = getattr(handoff, "coroutine", None) or handoff

        user_id = str(uuid4())
        thread_id = str(uuid4())
        captured_states: list[dict] = []

        async def capture_execute(
            ctx: object,
            stream_writer: object | None = None,
            integration_metadata: object | None = None,
            **kwargs: object,
        ) -> str:
            captured_states.append(ctx.initial_state)
            return "ok"

        fake_subagent_config = {"configurable": {"thread_id": f"notion_{thread_id}"}}

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(return_value=(MagicMock(), "notion_agent", "notion", False)),
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
                new=AsyncMock(return_value=SubagentOutcome(text="custom mcp result")),
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
        ctx_arg = mock_execute.call_args.kwargs.get("ctx") or mock_execute.call_args.args[0]
        assert ctx_arg.agent_name == f"custom_mcp_{custom_id}"
        assert ctx_arg.integration_id == custom_id

    async def test_custom_mcp_path_requires_user_id(self):
        """If user_id is None, the custom MCP path must return an error tuple
        without calling create_subagent_for_user."""

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
        assert "requires authentication" in error_or_id.lower() or "sign in" in error_or_id.lower()

    async def test_custom_mcp_path_returns_error_when_create_fails(self):
        """If create_subagent_for_user raises SubagentUnavailableError,
        _resolve_subagent must return an error tuple (not a graph)."""

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
                new=AsyncMock(side_effect=SubagentUnavailableError("exposed no usable tools")),
            ),
        ):
            graph, _, error_or_id, _ = await _resolve_subagent(
                subagent_id=custom_id,
                user_id="user-xyz",
            )

        assert graph is None
        assert "unavailable" in (error_or_id or "").lower()


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
        ):
            # Handoff to "gmail"
            with patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(return_value=(MagicMock(), "gmail_agent", "gmail", False)),
            ):
                await underlying(
                    subagent_id="gmail",
                    task="send email",
                    config=config,
                )

            # Handoff to "notion"
            with patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new=AsyncMock(return_value=(MagicMock(), "notion_agent", "notion", False)),
            ):
                await underlying(
                    subagent_id="notion",
                    task="take a note",
                    config=config,
                )

        assert len(captured_thread_ids) == 2
        thread_a, thread_b = captured_thread_ids
        # Thread IDs must differ for different subagents sharing the same parent thread
        assert thread_a != thread_b, f"Thread A ({thread_a}) must differ from Thread B ({thread_b})"
        # Both must embed the parent thread_id
        assert parent_thread_id in thread_a
        assert parent_thread_id in thread_b

    async def test_handoff_thread_id_encodes_integration_id(self):
        """The subagent thread ID must be prefixed with the integration ID so
        the format '{integration_id}_{parent_thread_id}' is preserved.

        The thread_id is assembled as '{int_id}_{thread_id}' in handoff() before
        being passed to build_agent_config(); we capture it there.
        """

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
                new=AsyncMock(return_value=SubagentOutcome(text="args test result")),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
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


# ---------------------------------------------------------------------------
# Test: HIL approval pause / resume through a real handoff
# ---------------------------------------------------------------------------

HANDOFF_APPROVAL_ID = "approval-handoff-1"
GATED_TASK = "post the release note to #eng"
GATED_ANSWER = "release note posted to #eng"


class _GatedSubagentLLM:
    """Posts the note, then finishes with the result. Message-driven, never counted.

    A HIL resume replays the executor's tool node and shows the model the same
    messages, so it must produce the same output — a call-sequence-driven fake
    would desync on the replay.
    """

    def __init__(self) -> None:
        self.invocations = 0

    def with_config(self, **_kwargs: Any) -> _GatedSubagentLLM:
        return self

    def bind_tools(self, _tools: Any, **_kwargs: Any) -> _GatedSubagentLLM:
        return self

    def with_retry(self, **_kwargs: Any) -> _GatedSubagentLLM:
        return self

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        self.invocations += 1
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc-finish-1", "name": "finish_task", "args": {"result": GATED_ANSWER}}
                ],
            )
        return AIMessage(
            content="",
            tool_calls=[
                {"id": "tc-post-1", "name": "post_release_note", "args": {"channel": "#eng"}}
            ],
        )


@pytest.fixture
def gated_effects() -> dict[str, int]:
    return {"post": 0}


@pytest.fixture
def gated_tool(gated_effects: dict[str, int]):
    @tool
    async def post_release_note(channel: str) -> str:
        """Post the release note to a channel, pausing for approval first."""
        decision = interrupt(
            {
                "type": "hil_approval",
                "approval_id": HANDOFF_APPROVAL_ID,
                "tool_name": "post_release_note",
            }
        )
        gated_effects["post"] += 1
        return f"posted to {channel} after {decision['status']}"

    return post_release_note


@pytest.fixture
async def gated_subagent(gated_tool):
    """A real provider subagent graph whose only integration tool gates on approval.

    Built through the production factory so the real middleware stack is in
    play — it is that stack's tool-invocation wrap chain that re-raises the
    GraphInterrupt as control flow; a bare tool node converts the pause into an
    error ToolMessage and no approval ever happens.
    """
    llm = _GatedSubagentLLM()
    saver = InMemorySaver()
    registry = SimpleNamespace(
        get_category_by_space=lambda _space: SimpleNamespace(
            tools=[SimpleNamespace(name=gated_tool.name, tool=gated_tool)]
        ),
        get_tool_dict=lambda: {gated_tool.name: gated_tool},
        get_category_of_tool=lambda _name: "general",
    )
    with (
        patch(f"{BASE_SUBAGENT_MODULE}.get_tool_registry", AsyncMock(return_value=registry)),
        patch(f"{BASE_SUBAGENT_MODULE}.get_tools_store", AsyncMock(return_value=InMemoryStore())),
        patch(
            f"{BASE_SUBAGENT_MODULE}.get_checkpointer_manager",
            AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: saver)),
        ),
        patch(f"{BASE_SUBAGENT_MODULE}.create_todo_tools", return_value=[]),
        patch(f"{BASE_SUBAGENT_MODULE}.create_todo_pre_model_hook", return_value=None),
        patch("app.agents.core.nodes.memory_node.memory_engine", MagicMock()),
    ):
        graph = await SubAgentFactory.create_provider_subagent(
            provider="gmail",
            name="gmail_agent",
            llm=llm,
            tool_space="gmail_delegated",
            use_direct_tools=True,
            disable_retrieve_tools=True,
        )
    return SimpleNamespace(graph=graph, llm=llm)


@pytest.fixture
def handoff_seams(gated_subagent):
    """External I/O only: provider lookup, prompt/context retrieval, Mongo reads."""
    with (
        patch(
            f"{HANDOFF_MODULE}._resolve_subagent",
            AsyncMock(return_value=(gated_subagent.graph, "gmail_agent", "gmail", False)),
        ),
        patch(
            f"{HANDOFF_MODULE}.create_subagent_system_message",
            AsyncMock(return_value=SystemMessage(content="You are the Gmail agent.")),
        ),
        patch(f"{HANDOFF_MODULE}.get_provider_metadata", AsyncMock(return_value=None)),
        patch(
            f"{HANDOFF_MODULE}.list_parked_subagents_for_conversation",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.core.subagents.subagent_runner.assemble_context",
            AsyncMock(
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                )
            ),
        ),
        patch(
            "app.utils.agent_utils.get_tool_registry",
            AsyncMock(return_value=SimpleNamespace(get_category_of_tool=lambda _name: "general")),
        ),
    ):
        yield


def _interrupt_payloads(events: list) -> list[dict[str, Any]]:
    """The HIL payloads the parent graph paused on during ``events``."""
    return [
        interrupt_payload(payload[LANGGRAPH_INTERRUPT_KEY])
        for mode, payload in events
        if mode == "updates" and isinstance(payload, dict) and LANGGRAPH_INTERRUPT_KEY in payload
    ]


class _ExecutorDriver:
    """Calls the real handoff tool from inside a parent node, as the executor does.

    A handoff drives its subagent imperatively, so the subagent's GraphInterrupt
    only becomes a pause if ``_run_blocking_handoff`` re-raises it into a parent
    runtime — which needs a real checkpointed parent graph around the call.
    """

    def __init__(self) -> None:
        self.results: list[str] = []
        underlying = handoff.coroutine

        async def tool_node(_state: MessagesState, config: RunnableConfig) -> dict:
            text = await underlying(
                subagent_id="gmail",
                task=GATED_TASK,
                config=config,
                tool_call_id="parent-tc-1",
            )
            self.results.append(text)
            return {"messages": [AIMessage(content=text)]}

        builder = StateGraph(MessagesState)
        builder.add_node("tools", tool_node)
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        self.graph = builder.compile(checkpointer=InMemorySaver())
        self.conversation_id = f"handoff-hil-{uuid4()}"

    @property
    def subagent_thread_id(self) -> str:
        return f"gmail_executor_{self.conversation_id}"

    async def run(self, resume: Any | None = None) -> list:
        configurable: dict[str, Any] = {
            "thread_id": f"executor_{self.conversation_id}",
            "conversation_id": self.conversation_id,
            "user_id": "user-hil-1",
        }
        if resume is not None:
            # The production contract: the executor's resume re-dispatch sets this,
            # and it is what arms the parked-checkpoint probe inside handoff().
            configurable[HIL_RESUME_CONFIG_KEY] = True
        payload = (
            Command(resume=resume)
            if resume is not None
            else {"messages": [HumanMessage(content="go")]}
        )
        return [
            event
            async for event in self.graph.astream(
                payload,
                config={"configurable": configurable},
                stream_mode=["updates", "custom"],
            )
        ]


def _approval_record(conversation_id: str, thread_id: str) -> HILApprovalRecord:
    return HILApprovalRecord(
        approval_id=HANDOFF_APPROVAL_ID,
        user_id="user-hil-1",
        conversation_id=conversation_id,
        stream_id="stream-hil-1",
        tool_name="post_release_note",
        status="approved",
        subagent_thread_id=thread_id,
        subagent_agent_name="gmail",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.integration
class TestHandoffHILPauseResume:
    """A gated tool inside a handed-off subagent must pause the executor and,
    once decided, resume from the subagent's checkpoint instead of re-running it."""

    async def test_a_gated_subagent_tool_parks_the_handoff_instead_of_answering(
        self, gated_subagent, gated_effects: dict[str, int], handoff_seams
    ) -> None:
        driver = _ExecutorDriver()

        events = await driver.run()

        paused = _interrupt_payloads(events)
        assert paused, "a gated tool inside a handoff must pause the executor, not answer"
        assert paused[0]["tool_name"] == "post_release_note"
        assert paused[0]["approval_id"] == HANDOFF_APPROVAL_ID
        assert gated_effects["post"] == 0, "nothing may run before the approval"
        assert driver.results == [], "handoff must not return a result while parked"
        snapshot = await gated_subagent.graph.aget_state(
            {"configurable": {"thread_id": driver.subagent_thread_id}}
        )
        assert snapshot.next, "the parked subagent is checkpointed so a decision can resume it"

    async def test_an_approved_handoff_resumes_the_checkpoint_and_acts_exactly_once(
        self, gated_subagent, gated_effects: dict[str, int], handoff_seams
    ) -> None:
        driver = _ExecutorDriver()
        await driver.run()
        calls_at_park = gated_subagent.llm.invocations

        events = await driver.run(resume={"status": "approved", "approval_id": HANDOFF_APPROVAL_ID})

        assert not _interrupt_payloads(events), "the executor finishes without re-pausing"
        assert gated_effects["post"] == 1, "the approved action runs exactly once"
        assert driver.results == [GATED_ANSWER], "the handoff returns the subagent's answer"
        assert gated_subagent.llm.invocations == calls_at_park + 1, (
            "the replay resumes the parked thread — it must not re-drive the model "
            "from the first turn"
        )

    async def test_resume_parked_subagent_continues_the_parked_thread(
        self, gated_subagent, gated_effects: dict[str, int], handoff_seams
    ) -> None:
        """The background-park collection path: everything is rebuilt from the
        approval record, and the subagent picks up at its interrupt."""
        driver = _ExecutorDriver()
        await driver.run()
        calls_at_park = gated_subagent.llm.invocations
        record = _approval_record(driver.conversation_id, driver.subagent_thread_id)

        outcome = await resume_parked_subagent(record, {"user_id": "user-hil-1"}, None)

        assert not outcome.paused
        assert outcome.text == GATED_ANSWER
        assert gated_effects["post"] == 1, "the approved action runs exactly once"
        assert gated_subagent.llm.invocations == calls_at_park + 1, (
            "resumed from the checkpoint, not restarted from an empty initial state"
        )

    async def test_resume_parked_subagent_refuses_when_the_checkpoint_is_gone(
        self, gated_subagent, gated_effects: dict[str, int], handoff_seams
    ) -> None:
        """Starting fresh would re-run the whole task from an empty state, so a
        record pointing at a thread with no checkpoint must fail loudly instead."""
        record = _approval_record("handoff-hil-missing", "gmail_executor_handoff-hil-missing")

        outcome = await resume_parked_subagent(record, {"user_id": "user-hil-1"}, None)

        assert "checkpoint is missing" in outcome.text
        assert gated_effects["post"] == 0, "nothing may run when there is nothing to resume"


# ---------------------------------------------------------------------------
# Test: background=True dispatch and dedup
# ---------------------------------------------------------------------------


@pytest.fixture
async def background_dispatch_seams():
    """External I/O only: subagent resolution, prompt/context retrieval, and the
    actual background execution (asyncio.create_task'd, never awaited by the
    caller — mocked so the test verifies dispatch/dedup mechanics, not a real
    subagent run). try_claim_bg_dispatch's real Redis call is intentionally NOT
    mocked — the durable dedup guard is the point of this test — so it needs
    real Redis: skip before dialing when the run is not opted into real
    services (same pattern as the pg_checkpointer fixtures).
    """
    if os.environ.get("USE_REAL_SERVICES") != "1":
        pytest.skip("background-dispatch dedup guard needs real Redis (USE_REAL_SERVICES=1)")
    from app.db.redis import redis_cache

    redis_cache.redis = None  # next `.client` access lazily reconnects on THIS loop
    fresh_client = redis_cache.client
    await fresh_client.ping()

    mock_graph = MagicMock()
    run_bg = AsyncMock(return_value=None)
    spawned: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def _tracking_create_task(coro, **kwargs):
        task = real_create_task(coro, **kwargs)
        spawned.append(task)
        return task

    with (
        patch(
            f"{HANDOFF_MODULE}._resolve_subagent",
            AsyncMock(return_value=(mock_graph, "gmail_agent", "gmail", False)),
        ),
        patch(
            f"{HANDOFF_MODULE}.create_subagent_system_message",
            AsyncMock(return_value=SystemMessage(content="You are the Gmail agent.")),
        ),
        patch(f"{HANDOFF_MODULE}.get_provider_metadata", AsyncMock(return_value=None)),
        patch(
            f"{HANDOFF_MODULE}.list_parked_subagents_for_conversation",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.core.subagents.subagent_runner.assemble_context",
            AsyncMock(
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                )
            ),
        ),
        patch(
            "app.utils.agent_utils.get_tool_registry",
            AsyncMock(return_value=SimpleNamespace(get_category_of_tool=lambda _name: "general")),
        ),
        patch(f"{HANDOFF_MODULE}.run_subagent_background", run_bg),
        patch("app.utils.background_tasks.asyncio.create_task", side_effect=_tracking_create_task),
    ):
        yield run_bg
        # handoff(background=True) fire-and-forgets its subagent task via
        # spawn_background_task — drain exactly the task(s) THIS test spawned
        # (captured via the wrapper above) so none outlive this test's event
        # loop and raise "Event loop is closed" as an orphaned-task warning.
        pending = [t for t in spawned if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await fresh_client.aclose()
        redis_cache.redis = None


@pytest.mark.integration
class TestBackgroundSubagentDispatch:
    """A background=True handoff must spawn exactly once per distinct tool call
    and reject a second dispatch for the same (conversation, tool_call_id) pair —
    the node re-runs on a HIL-join replay, and re-spawning would double the
    subagent's real-world side effects."""

    async def test_background_dispatch_returns_started_message_and_spawns_once(
        self, background_dispatch_seams
    ) -> None:
        stream_id = f"stream-bg-{uuid4()}"
        conversation_id = f"conv-bg-{uuid4()}"
        config = {
            "configurable": {
                "user_id": "user-bg-1",
                "thread_id": conversation_id,
                "conversation_id": conversation_id,
                "stream_id": stream_id,
            }
        }

        result = await handoff.coroutine(
            subagent_id="gmail",
            task="triage overnight email",
            config=config,
            background=True,
            tool_call_id="tc-bg-1",
        )

        assert "started in background" in result
        assert "gmail_agent" in result
        background_dispatch_seams.assert_called_once()

    async def test_duplicate_dispatch_same_tool_call_id_is_deduplicated(
        self, background_dispatch_seams
    ) -> None:
        """Simulates a HIL-join replay: the node re-runs with a fresh stream_id
        (a new SSE connection on resume), but conversation_id and tool_call_id
        are checkpointed and stable — the durable Redis guard, not the in-memory
        per-stream integration claim, is what must catch this duplicate."""
        conversation_id = f"conv-bg-{uuid4()}"

        def _config(stream_id: str) -> dict:
            return {
                "configurable": {
                    "user_id": "user-bg-1",
                    "thread_id": conversation_id,
                    "conversation_id": conversation_id,
                    "stream_id": stream_id,
                }
            }

        first = await handoff.coroutine(
            subagent_id="gmail",
            task="triage overnight email",
            config=_config(f"stream-bg-{uuid4()}"),
            background=True,
            tool_call_id="tc-bg-dup-1",
        )
        second = await handoff.coroutine(
            subagent_id="gmail",
            task="triage overnight email",
            config=_config(f"stream-bg-{uuid4()}"),
            background=True,
            tool_call_id="tc-bg-dup-1",
        )

        assert "started in background" in first
        assert "started in background" in second
        assert background_dispatch_seams.call_count == 1, (
            "the second dispatch with the same tool_call_id must not re-spawn the subagent"
        )
