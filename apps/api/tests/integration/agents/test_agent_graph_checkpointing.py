"""Integration tests for Agent Graph with Real PostgreSQL Checkpointing.

Tests the production graph builder and checkpointer manager with a real
PostgreSQL database. The LLM is replaced with BindableToolsFakeModel to
avoid external API calls, but the graph compilation, state management,
pre-model hooks, and PostgreSQL checkpointing all run for real.

If any of these production modules are deleted or broken, these tests
will fail immediately:
- app.agents.core.graph_builder.build_graph.build_comms_graph
- app.agents.core.graph_builder.checkpointer_manager.CheckpointerManager
- app.agents.core.nodes.filter_messages.filter_messages_node
- app.agents.core.nodes.manage_system_prompts.manage_system_prompts_node
- app.override.langgraph_bigtool.create_agent.create_agent

Requires: PostgreSQL running at localhost:5432 with database gaia_test.
"""

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.hooks import HookType
from tests.helpers import (
    create_fake_llm,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

import os

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL", "postgresql://gaia:gaia@localhost:5432/gaia_test"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread_config(extra: dict[str, Any] | None = None) -> dict:
    """Return a LangGraph config dict with a unique thread_id and user_id."""
    configurable: dict[str, Any] = {
        "thread_id": str(uuid4()),
        "user_id": str(uuid4()),
    }
    if extra:
        configurable.update(extra)
    return {"configurable": configurable}


def _make_store_mock() -> MagicMock:
    """Return a mock that satisfies langgraph.store.base.BaseStore."""
    store = MagicMock()
    store.aget = AsyncMock(return_value=None)
    store.aput = AsyncMock(return_value=None)
    store.asearch = AsyncMock(return_value=[])
    store.alist_namespaces = AsyncMock(return_value=[])
    return store


def _follow_up_io_patches() -> list:
    """Return patches for follow_up_actions_node I/O boundaries."""
    return [
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
            new_callable=AsyncMock,
            return_value=AIMessage(
                content='{"actions": ["Action 1", "Action 2", "Action 3", "Action 4"]}'
            ),
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
            new_callable=AsyncMock,
            return_value={"tool_names": []},
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=lambda _: None,
        ),
    ]


@contextlib.contextmanager
def _apply_patches(store_mock: MagicMock, extra_patches: list | None = None):
    """Apply all boundary mocks needed to build the comms graph."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.agents.tools.core.store.providers.aget",
                new_callable=AsyncMock,
                return_value=store_mock,
            )
        )
        stack.enter_context(
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=None,
            )
        )
        for p in _follow_up_io_patches():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                return_value=(None, "executor not available in tests"),
            )
        )
        stack.enter_context(
            patch(
                "app.agents.tools.memory_tools.memory_service",
                new_callable=MagicMock,
            )
        )
        for p in extra_patches or []:
            stack.enter_context(p)
        yield


@contextlib.contextmanager
def _apply_patches_with_checkpointer(
    store_mock: MagicMock,
    checkpointer_manager: CheckpointerManager,
    extra_patches: list | None = None,
):
    """Apply patches but supply a REAL checkpointer manager instead of None."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.agents.tools.core.store.providers.aget",
                new_callable=AsyncMock,
                return_value=store_mock,
            )
        )
        stack.enter_context(
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=checkpointer_manager,
            )
        )
        for p in _follow_up_io_patches():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                return_value=(None, "executor not available in tests"),
            )
        )
        stack.enter_context(
            patch(
                "app.agents.tools.memory_tools.memory_service",
                new_callable=MagicMock,
            )
        )
        for p in extra_patches or []:
            stack.enter_context(p)
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_checkpointer():
    """Create a real AsyncPostgresSaver backed by test PostgreSQL.

    Sets up the checkpoint tables and yields the checkpointer.
    Cleans up the connection pool on teardown.
    Skips the test if PostgreSQL is not reachable.
    """
    connection_kwargs = {
        "autocommit": True,
        "prepare_threshold": 0,
    }
    pool = AsyncConnectionPool(
        conninfo=POSTGRES_TEST_URL,
        max_size=5,
        kwargs=connection_kwargs,
        open=False,
        timeout=10,
    )
    try:
        await pool.open(wait=True, timeout=10)
    except Exception:
        if os.environ.get("USE_REAL_SERVICES", "1") == "1":
            raise  # In CI with real services, Postgres must be running
        pytest.skip("PostgreSQL not available at " + POSTGRES_TEST_URL)

    checkpointer = AsyncPostgresSaver(conn=pool)
    await checkpointer.setup()

    yield checkpointer

    await pool.close()


@pytest.fixture
async def pg_checkpointer_manager():
    """Create a real CheckpointerManager backed by test PostgreSQL.

    Uses the production CheckpointerManager class directly.
    Skips the test if PostgreSQL is not reachable.
    """
    manager = CheckpointerManager(conninfo=POSTGRES_TEST_URL, max_pool_size=5)
    try:
        await manager.setup()
    except Exception:
        pytest.skip("PostgreSQL not available at " + POSTGRES_TEST_URL)

    yield manager

    await manager.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGraphCompilationWithPostgres:
    """Test 1: Graph compilation with real PostgreSQL checkpointer."""

    async def test_comms_graph_compiles_with_postgres_checkpointer(
        self, pg_checkpointer_manager
    ):
        """build_comms_graph compiles successfully when backed by a real
        PostgreSQL checkpointer manager. The compiled graph must expose
        the standard LangGraph API (ainvoke, astream, aget_state)."""
        store_mock = _make_store_mock()
        fake_llm = create_fake_llm(["ok"])

        with _apply_patches_with_checkpointer(store_mock, pg_checkpointer_manager):
            async with build_comms_graph(chat_llm=fake_llm) as graph:
                assert graph is not None
                assert hasattr(graph, "ainvoke")
                assert hasattr(graph, "astream")
                assert hasattr(graph, "aget_state")

    async def test_comms_graph_compiles_with_in_memory_fallback(self):
        """When checkpointer_manager returns None, build_comms_graph falls
        back to InMemorySaver without error."""
        store_mock = _make_store_mock()
        fake_llm = create_fake_llm(["ok"])

        with _apply_patches(store_mock):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                assert graph is not None
                assert hasattr(graph, "ainvoke")


@pytest.mark.integration
class TestMultiTurnConversation:
    """Test 2: Multi-turn conversation with state persistence across turns."""

    async def test_second_turn_sees_first_turn_messages(self, pg_checkpointer):
        """Invoke the graph twice with the same thread_id. The second
        invocation must see messages from the first turn, proving
        PostgreSQL checkpointing persists state across turns."""
        fake_llm = create_fake_llm(["Response to turn 1", "Response to turn 2"])

        from langgraph.store.memory import InMemoryStore

        pre_model_hooks: list[HookType] = [
            filter_messages_node,
            manage_system_prompts_node,
        ]

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=pre_model_hooks,
        )

        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()

        # Turn 1
        result1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello, first turn")]},
            config=config,
        )
        msgs_after_turn1 = result1["messages"]
        human_msgs_t1 = [m for m in msgs_after_turn1 if isinstance(m, HumanMessage)]
        assert len(human_msgs_t1) == 1

        # Turn 2 on same thread
        result2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello, second turn")]},
            config=config,
        )
        msgs_after_turn2 = result2["messages"]
        human_msgs_t2 = [m for m in msgs_after_turn2 if isinstance(m, HumanMessage)]

        # Both human messages must be present (state accumulated)
        assert len(human_msgs_t2) == 2, (
            f"Expected 2 human messages across turns, got {len(human_msgs_t2)}"
        )
        contents = [m.content for m in human_msgs_t2]
        assert "Hello, first turn" in contents
        assert "Hello, second turn" in contents

    async def test_different_threads_are_isolated_in_postgres(self, pg_checkpointer):
        """Two different thread_ids must have completely independent state
        even when sharing the same PostgreSQL checkpointer."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["Reply A", "Reply B"])

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )

        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config_a = _thread_config()
        config_b = _thread_config()

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Thread A message")]},
            config=config_a,
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Thread B message")]},
            config=config_b,
        )

        state_a = await graph.aget_state(config_a)
        state_b = await graph.aget_state(config_b)

        human_a = [
            m.content for m in state_a.values["messages"] if isinstance(m, HumanMessage)
        ]
        human_b = [
            m.content for m in state_b.values["messages"] if isinstance(m, HumanMessage)
        ]

        assert "Thread A message" in human_a
        assert "Thread B message" not in human_a
        assert "Thread B message" in human_b
        assert "Thread A message" not in human_b


@pytest.mark.integration
class TestStatePersistence:
    """Test 3: Verify state is actually written to PostgreSQL."""

    async def test_checkpoint_written_to_postgres(self, pg_checkpointer):
        """After graph invocation, querying the checkpointer directly via
        aget_tuple must return a valid checkpoint with the conversation state."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["Persisted response"])

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )

        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()
        thread_id = config["configurable"]["thread_id"]

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Checkpoint test message")]},
            config=config,
        )

        # Query the checkpointer directly
        checkpoint_tuple = await pg_checkpointer.aget_tuple(config)
        assert checkpoint_tuple is not None, (
            "Checkpoint must exist in PostgreSQL after invocation"
        )
        assert checkpoint_tuple.checkpoint is not None
        assert checkpoint_tuple.config is not None

        # The checkpoint config must reference our thread_id
        stored_thread_id = checkpoint_tuple.config.get("configurable", {}).get(
            "thread_id"
        )
        assert stored_thread_id == thread_id, (
            f"Checkpoint thread_id mismatch: expected {thread_id}, got {stored_thread_id}"
        )

    async def test_state_values_match_after_persistence(self, pg_checkpointer):
        """The state retrieved via aget_state after invocation must contain
        the messages we sent plus the AI response."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["State values response"])

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )

        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()

        await graph.ainvoke(
            {"messages": [HumanMessage(content="Verify state values")]},
            config=config,
        )

        state = await graph.aget_state(config)
        values = state.values

        assert "messages" in values
        assert "selected_tool_ids" in values
        assert isinstance(values["messages"], list)

        # Must contain the human message and the AI response
        human_msgs = [m for m in values["messages"] if isinstance(m, HumanMessage)]
        ai_msgs = [m for m in values["messages"] if isinstance(m, AIMessage)]

        assert len(human_msgs) >= 1
        assert any(m.content == "Verify state values" for m in human_msgs)
        assert len(ai_msgs) >= 1
        assert any(m.content == "State values response" for m in ai_msgs)


@pytest.mark.integration
class TestCheckpointRecovery:
    """Test 4: Checkpoint recovery with a new graph instance."""

    async def test_new_graph_instance_recovers_state(self, pg_checkpointer):
        """Build a graph, invoke it, then build a SECOND graph instance
        with the same checkpointer. Invoking the second graph with the
        same thread_id must recover the conversation state from the first."""
        from langgraph.store.memory import InMemoryStore

        fake_llm_1 = create_fake_llm(["First graph response"])
        fake_llm_2 = create_fake_llm(["Second graph response"])

        hooks: list[HookType] = [filter_messages_node, manage_system_prompts_node]
        store = InMemoryStore()
        config = _thread_config()

        # Graph instance 1
        builder1 = create_agent(
            llm=fake_llm_1,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph1 = builder1.compile(checkpointer=pg_checkpointer, store=store)

        await graph1.ainvoke(
            {"messages": [HumanMessage(content="Message from graph 1")]},
            config=config,
        )

        # Graph instance 2 (new compilation, same checkpointer)
        builder2 = create_agent(
            llm=fake_llm_2,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph2 = builder2.compile(checkpointer=pg_checkpointer, store=store)

        # Invoke on same thread: graph2 should see graph1's state
        result = await graph2.ainvoke(
            {"messages": [HumanMessage(content="Message from graph 2")]},
            config=config,
        )

        human_msgs = [m for m in result["messages"] if isinstance(m, HumanMessage)]
        contents = [m.content for m in human_msgs]

        assert "Message from graph 1" in contents, (
            "Graph 2 must recover messages from graph 1 via PostgreSQL checkpoint"
        )
        assert "Message from graph 2" in contents, (
            "Graph 2 must also contain its own input message"
        )

    async def test_recovery_preserves_ai_responses(self, pg_checkpointer):
        """After recovery, AI responses from the first graph instance must
        be present in the recovered state."""
        from langgraph.store.memory import InMemoryStore

        fake_llm_1 = create_fake_llm(["AI response from first session"])
        fake_llm_2 = create_fake_llm(["AI response from second session"])

        hooks: list[HookType] = [filter_messages_node, manage_system_prompts_node]
        store = InMemoryStore()
        config = _thread_config()

        builder1 = create_agent(
            llm=fake_llm_1,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph1 = builder1.compile(checkpointer=pg_checkpointer, store=store)

        await graph1.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=config,
        )

        # Build new graph, same checkpointer, same thread
        builder2 = create_agent(
            llm=fake_llm_2,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph2 = builder2.compile(checkpointer=pg_checkpointer, store=store)

        result = await graph2.ainvoke(
            {"messages": [HumanMessage(content="Continue")]},
            config=config,
        )

        ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        ai_contents = [m.content for m in ai_msgs]

        # The AI response from graph1 must have been recovered
        assert any("AI response from first session" in c for c in ai_contents), (
            f"AI response from first session not found in recovered state. "
            f"Got: {ai_contents}"
        )


@pytest.mark.integration
class TestPreModelHooksExecution:
    """Test 5: Verify pre-model hooks (filter_messages_node,
    manage_system_prompts_node) actually execute during graph runs."""

    async def test_filter_messages_node_runs_during_execution(self, pg_checkpointer):
        """Seed the graph with a dangling (unanswered) tool call. If
        filter_messages_node runs correctly, the dangling tool call is
        stripped before the LLM sees it, and the graph completes without
        error. If filter_messages_node is deleted, the graph will either
        crash or pass invalid state to the LLM."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["Response after filtering"])

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )
        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()

        # AIMessage with unanswered tool call (no matching ToolMessage)
        dangling_ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "some_tool",
                    "args": {"x": 1},
                    "id": "dangling_001",
                    "type": "tool_call",
                }
            ],
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content="Start"),
                    dangling_ai,
                ]
            },
            config=config,
        )

        # Graph completed: filter_messages_node stripped the dangling call
        ai_msgs = [
            m
            for m in result["messages"]
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
        ]
        assert len(ai_msgs) >= 1, (
            "Graph should produce a clean AI response after filter_messages_node "
            "strips the dangling tool call"
        )

    async def test_manage_system_prompts_keeps_latest_only(self, pg_checkpointer):
        """Send multiple non-memory system prompts. The
        manage_system_prompts_node keeps only the latest one before the
        LLM call, but the checkpoint retains all of them (pre-model hooks
        modify state ephemerally). The graph must complete without error."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["System prompt managed"])

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )
        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()

        result = await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="Old system prompt"),
                    HumanMessage(content="First"),
                    SystemMessage(content="New system prompt"),
                    HumanMessage(content="Second"),
                ]
            },
            config=config,
        )

        # Both system prompts remain in persisted state (pre-model hooks
        # only modify ephemerally for the LLM call)
        system_msgs = [m for m in result["messages"] if m.type == "system"]
        non_memory = [
            m
            for m in system_msgs
            if not m.additional_kwargs.get("memory_message", False)
        ]
        assert len(non_memory) == 2, (
            f"Both system prompts should remain in persisted state, found {len(non_memory)}"
        )

        # Graph completed with AI response
        ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_msgs) >= 1

    async def test_graph_fails_if_hooks_raise(self, pg_checkpointer):
        """If the pre-model hooks raise an unhandled exception, the error
        must propagate to the caller. This validates that the hooks are
        actually wired into the execution path."""
        from langgraph.store.memory import InMemoryStore

        fake_llm = create_fake_llm(["Should not reach"])

        sentinel = RuntimeError("hooks-execution-sentinel-error")

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=[filter_messages_node, manage_system_prompts_node],
        )
        graph = builder.compile(checkpointer=pg_checkpointer, store=InMemoryStore())

        config = _thread_config()

        with patch(
            "app.override.langgraph_bigtool.create_agent.execute_hooks",
            side_effect=sentinel,
        ):
            with pytest.raises(RuntimeError, match="hooks-execution-sentinel-error"):
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="Trigger")]},
                    config=config,
                )


@pytest.mark.integration
class TestErrorDuringInvocation:
    """Test 6: Error during invocation must not corrupt checkpointed state."""

    async def test_llm_error_does_not_corrupt_state(self, pg_checkpointer):
        """Invoke the graph successfully once, then invoke again with an LLM
        that raises. After the error, the checkpointed state from the first
        turn must still be intact and retrievable."""
        from langgraph.store.memory import InMemoryStore

        hooks: list[HookType] = [filter_messages_node, manage_system_prompts_node]
        store = InMemoryStore()
        config = _thread_config()

        # Turn 1: successful invocation
        fake_llm_ok = create_fake_llm(["Successful first response"])

        builder1 = create_agent(
            llm=fake_llm_ok,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph1 = builder1.compile(checkpointer=pg_checkpointer, store=store)

        await graph1.ainvoke(
            {"messages": [HumanMessage(content="Good message")]},
            config=config,
        )

        # Capture state after successful turn
        state_before_error = await graph1.aget_state(config)
        _msg_count_before = len(state_before_error.values["messages"])

        # Turn 2: LLM raises an error
        class ErrorLLM(FakeMessagesListChatModel):
            def bind_tools(self, tools: Any, **kwargs: Any) -> "ErrorLLM":
                return self

            async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
                raise ValueError("Simulated LLM failure")

        error_llm = ErrorLLM(responses=[])

        builder2 = create_agent(
            llm=error_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph2 = builder2.compile(checkpointer=pg_checkpointer, store=store)

        with pytest.raises(ValueError, match="Simulated LLM failure"):
            await graph2.ainvoke(
                {"messages": [HumanMessage(content="This will fail")]},
                config=config,
            )

        # Verify state is not corrupted: retrieve state from a third graph instance
        fake_llm_3 = create_fake_llm(["Recovery response"])
        builder3 = create_agent(
            llm=fake_llm_3,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph3 = builder3.compile(checkpointer=pg_checkpointer, store=store)

        state_after_error = await graph3.aget_state(config)

        # The checkpoint must still be valid and contain the messages from turn 1
        assert state_after_error is not None
        assert "messages" in state_after_error.values

        human_msgs = [
            m
            for m in state_after_error.values["messages"]
            if isinstance(m, HumanMessage)
        ]
        assert any(m.content == "Good message" for m in human_msgs), (
            "First turn's human message must survive the failed second invocation"
        )

        ai_msgs = [
            m for m in state_after_error.values["messages"] if isinstance(m, AIMessage)
        ]
        assert any("Successful first response" in m.content for m in ai_msgs), (
            "First turn's AI response must survive the failed second invocation"
        )

    async def test_state_recoverable_after_error(self, pg_checkpointer):
        """After an LLM error, a subsequent successful invocation on the
        same thread must work correctly, accumulating onto the pre-error state."""
        from langgraph.store.memory import InMemoryStore

        hooks: list[HookType] = [filter_messages_node, manage_system_prompts_node]
        store = InMemoryStore()
        config = _thread_config()

        # Turn 1: success
        fake_llm_1 = create_fake_llm(["Turn 1 OK"])
        builder1 = create_agent(
            llm=fake_llm_1,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph1 = builder1.compile(checkpointer=pg_checkpointer, store=store)

        await graph1.ainvoke(
            {"messages": [HumanMessage(content="First OK")]},
            config=config,
        )

        # Turn 2: error
        class BrokenLLM(FakeMessagesListChatModel):
            def bind_tools(self, tools: Any, **kwargs: Any) -> "BrokenLLM":
                return self

            async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
                raise ConnectionError("Network failure")

        broken_llm = BrokenLLM(responses=[])
        builder2 = create_agent(
            llm=broken_llm,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph2 = builder2.compile(checkpointer=pg_checkpointer, store=store)

        with pytest.raises(ConnectionError):
            await graph2.ainvoke(
                {"messages": [HumanMessage(content="This fails")]},
                config=config,
            )

        # Turn 3: recovery
        fake_llm_3 = create_fake_llm(["Turn 3 recovery"])
        builder3 = create_agent(
            llm=fake_llm_3,
            agent_name="test_agent",
            tool_registry={},
            disable_retrieve_tools=True,
            initial_tool_ids=[],
            middleware=None,
            pre_model_hooks=hooks,
        )
        graph3 = builder3.compile(checkpointer=pg_checkpointer, store=store)

        result = await graph3.ainvoke(
            {"messages": [HumanMessage(content="Third OK")]},
            config=config,
        )

        human_msgs = [m for m in result["messages"] if isinstance(m, HumanMessage)]
        contents = [m.content for m in human_msgs]

        # Turn 1 message must be present (recovered from checkpoint)
        assert "First OK" in contents, (
            "First turn message must be present after recovery"
        )
        # Turn 3 message must be present
        assert "Third OK" in contents, "Third turn message must be present"
        # AI responses from both successful turns
        ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_msgs) >= 2, "Must have AI responses from both successful turns"


@pytest.mark.integration
class TestCheckpointerManagerProduction:
    """Test the production CheckpointerManager class directly."""

    async def test_checkpointer_manager_setup_and_get(self):
        """CheckpointerManager.setup() must initialize the pool and
        checkpointer. get_checkpointer() must return a usable saver."""
        manager = CheckpointerManager(conninfo=POSTGRES_TEST_URL, max_pool_size=5)
        try:
            await manager.setup()
        except Exception:
            pytest.skip("PostgreSQL not available at " + POSTGRES_TEST_URL)

        try:
            checkpointer = manager.get_checkpointer()
            assert checkpointer is not None
            assert isinstance(checkpointer, AsyncPostgresSaver)
        finally:
            await manager.close()

    async def test_get_checkpointer_before_setup_raises(self):
        """Calling get_checkpointer() before setup() must raise RuntimeError."""
        manager = CheckpointerManager(conninfo=POSTGRES_TEST_URL)

        with pytest.raises(RuntimeError, match="not been initialized"):
            manager.get_checkpointer()

    async def test_checkpointer_manager_close_is_idempotent(self):
        """Calling close() multiple times must not raise."""
        manager = CheckpointerManager(conninfo=POSTGRES_TEST_URL, max_pool_size=5)
        try:
            await manager.setup()
        except Exception:
            pytest.skip("PostgreSQL not available at " + POSTGRES_TEST_URL)
        await manager.close()
        # Second close should not raise
        await manager.close()


@pytest.mark.integration
class TestFullCommsGraphWithPostgres:
    """Integration test using the full production build_comms_graph with
    PostgreSQL checkpointing (not in_memory_checkpointer=True)."""

    async def test_full_comms_graph_with_real_postgres(self, pg_checkpointer_manager):
        """Build the real comms graph backed by PostgreSQL and invoke it.
        The graph must complete and persist state to PostgreSQL."""
        store_mock = _make_store_mock()
        fake_llm = create_fake_llm(["Hello from Postgres-backed graph!"])

        config = _thread_config()

        with _apply_patches_with_checkpointer(store_mock, pg_checkpointer_manager):
            async with build_comms_graph(chat_llm=fake_llm) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Test Postgres comms")]},
                    config=config,
                )

                # Verify graph completed
                ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
                assert len(ai_msgs) >= 1

                # Verify state was checkpointed
                state = await graph.aget_state(config)
                assert state is not None
                assert len(state.values["messages"]) >= 2  # human + AI

    async def test_full_comms_graph_multi_turn_postgres(self, pg_checkpointer_manager):
        """Two-turn conversation through the full production comms graph
        with PostgreSQL. State must accumulate across turns."""
        store_mock = _make_store_mock()
        fake_llm = create_fake_llm(["Turn 1 reply", "Turn 2 reply"])

        config = _thread_config()

        with _apply_patches_with_checkpointer(store_mock, pg_checkpointer_manager):
            async with build_comms_graph(chat_llm=fake_llm) as graph:
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="Postgres turn 1")]},
                    config=config,
                )

                state1 = await graph.aget_state(config)
                count1 = len(state1.values["messages"])

                await graph.ainvoke(
                    {"messages": [HumanMessage(content="Postgres turn 2")]},
                    config=config,
                )

                state2 = await graph.aget_state(config)
                count2 = len(state2.values["messages"])

                assert count2 > count1, (
                    "Messages must accumulate across turns with PostgreSQL checkpointing"
                )

                human_msgs = [
                    m for m in state2.values["messages"] if isinstance(m, HumanMessage)
                ]
                contents = [m.content for m in human_msgs]
                assert "Postgres turn 1" in contents
                assert "Postgres turn 2" in contents
