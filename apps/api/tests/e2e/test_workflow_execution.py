"""E2E test: GAIA graph lifecycle — compile, invoke, checkpoint, and state integrity.

WHAT THIS TESTS (REAL GAIA CODE):
- ``build_comms_graph`` from ``app.agents.core.graph_builder.build_graph``
  can be constructed with in_memory_checkpointer=True (uses InMemorySaver
  instead of PostgreSQL — a production flag).
- The GAIA ``State`` schema from ``app.override.langgraph_bigtool.utils``
  contains the ``todos`` channel, ``selected_tool_ids``, and ``messages``.
- ``MemorySaver`` checkpointing accumulates state across multiple graph turns.
- Graph thread isolation: separate thread_ids produce independent state.
- ``create_agent`` (real GAIA override) compiles a graph that uses the
  GAIA ``State`` TypedDict, not the generic LangGraph ``MessagesState``.

Mock surfaces:
- LLM: BindableToolsFakeModel (wraps FakeMessagesListChatModel with bind_tools support)
- store: InMemoryStore (no ChromaDB, no real tool indexing)
- Checkpointer: MemorySaver (no PostgreSQL)
- External API calls (memory service, tool registry): mocked via patch

DELETE ``app/agents/core/graph_builder/build_graph.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/utils.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from app.override.langgraph_bigtool.utils import State
from tests.e2e.conftest import build_gaia_test_graph, make_gaia_state
from tests.factories import make_config
from tests.helpers import BindableToolsFakeModel


@pytest.mark.e2e
class TestWorkflowExecution:
    """E2E tests for GAIA graph lifecycle and state schema correctness."""

    async def test_gaia_state_schema_has_todos_channel(self):
        """GAIA State must include the 'todos' channel (GAIA-specific extension).

        State from app.override.langgraph_bigtool.utils extends the upstream
        langgraph_bigtool State with a 'todos' channel. This test verifies
        that channel exists in the schema.

        If app/override/langgraph_bigtool/utils.py is deleted or the 'todos'
        channel is removed, this test will fail.
        """
        state_fields = State.__annotations__
        assert "todos" in state_fields, (
            "GAIA State must have a 'todos' channel. "
            "This channel is used by plan_tasks and update_tasks tools."
        )

    async def test_gaia_state_schema_has_messages_channel(self):
        """GAIA State must include the 'messages' channel (from MessagesState)."""
        state_fields = State.__annotations__
        assert "messages" in state_fields, (
            "GAIA State must have a 'messages' channel inherited from bigtool State."
        )

    async def test_gaia_state_schema_has_selected_tool_ids_channel(self):
        """GAIA State must include 'selected_tool_ids' (used by bigtool tool retrieval)."""
        state_fields = State.__annotations__
        assert "selected_tool_ids" in state_fields, (
            "GAIA State must have 'selected_tool_ids' channel from bigtool State."
        )

    async def test_compiled_graph_returns_gaia_state_on_invoke(
        self, thread_config, in_memory_store, memory_saver
    ):
        """A compiled GAIA graph must return state with GAIA-specific channels.

        When ainvoke() returns, the result dict must contain 'todos' and
        'selected_tool_ids' — channels that exist only in the GAIA State schema,
        not in generic LangGraph MessagesState.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="Workflow complete.")]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run the workflow")]},
            config=thread_config,
        )

        assert "messages" in result
        assert "todos" in result, (
            "Graph result must include 'todos' (GAIA State channel). "
            "This confirms the graph uses GAIA State, not generic MessagesState."
        )
        assert "selected_tool_ids" in result, (
            "Graph result must include 'selected_tool_ids' (GAIA bigtool State channel)."
        )

    async def test_checkpointing_accumulates_messages_across_turns(
        self, in_memory_store, memory_saver
    ):
        """MemorySaver checkpointing must accumulate messages across multiple invocations.

        This tests that the same thread_id produces accumulated state after
        multiple calls — the same pattern used by build_comms_graph in production.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(content="Response to first message."),
                AIMessage(content="Response to second message."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        thread_id = str(uuid4())
        user_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

        # First invocation
        await graph.ainvoke(
            {"messages": [HumanMessage(content="First message")]},
            config=config,
        )

        # Second invocation on the SAME thread
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Second message")]},
            config=config,
        )

        state_snapshot = await graph.aget_state(config)
        accumulated = state_snapshot.values["messages"]

        # Should have: HumanMessage1, AIMessage1, HumanMessage2, AIMessage2
        assert len(accumulated) == 4, (
            f"Expected 4 accumulated messages after 2 turns, got {len(accumulated)}. "
            "MemorySaver checkpointing must accumulate state across turns."
        )

    async def test_different_thread_ids_have_independent_state(
        self, in_memory_store
    ):
        """Separate thread_ids must not share state (thread isolation).

        This mirrors how the production comms agent handles concurrent users:
        each conversation thread is completely isolated.
        """
        checkpointer = MemorySaver()

        fake_llm_a = BindableToolsFakeModel(
            responses=[AIMessage(content="Response for thread A.")]
        )
        fake_llm_b = BindableToolsFakeModel(
            responses=[AIMessage(content="Response for thread B.")]
        )

        graph_a = build_gaia_test_graph(
            fake_llm=fake_llm_a,
            tool_registry={},
            checkpointer=checkpointer,
            store=in_memory_store,
        )
        graph_b = build_gaia_test_graph(
            fake_llm=fake_llm_b,
            tool_registry={},
            checkpointer=checkpointer,
            store=in_memory_store,
        )

        config_a = {"configurable": {"thread_id": "thread-alpha", "user_id": str(uuid4())}}
        config_b = {"configurable": {"thread_id": "thread-beta", "user_id": str(uuid4())}}

        await graph_a.ainvoke(
            {"messages": [HumanMessage(content="Message from A")]}, config=config_a
        )
        await graph_b.ainvoke(
            {"messages": [HumanMessage(content="Message from B")]}, config=config_b
        )

        state_a = await graph_a.aget_state(config_a)
        state_b = await graph_b.aget_state(config_b)

        last_a = state_a.values["messages"][-1].content
        last_b = state_b.values["messages"][-1].content

        assert "thread A" in last_a.lower() or "a" in last_a.lower(), (
            f"Thread A state should contain thread-A response, got: {last_a}"
        )
        assert "thread B" in last_b.lower() or "b" in last_b.lower(), (
            f"Thread B state should contain thread-B response, got: {last_b}"
        )
        assert last_a != last_b, "Different threads must have independent state"

    async def test_build_comms_graph_accepts_in_memory_checkpointer_flag(self):
        """build_comms_graph must compile with in_memory_checkpointer=True.

        This exercises the real build_comms_graph function from build_graph.py.
        When in_memory_checkpointer=True, it should use InMemorySaver instead of
        the PostgreSQL checkpointer — which is exactly what tests need.

        If build_graph.py is deleted, this test fails immediately on import.
        """
        # Import the real build_comms_graph from production code
        from app.agents.core.graph_builder.build_graph import build_comms_graph

        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="Comms agent response.")]
        )

        # Patch the external dependencies that build_comms_graph uses.
        # Patch targets must be the names as imported in build_graph.py.
        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=InMemoryStore()),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_comms_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=[],
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value=AIMessage(content='{"actions": []}')),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=lambda _: None,
            ),
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new=AsyncMock(return_value=(None, "executor not available in tests")),
            ),
            patch(
                "app.agents.tools.memory_tools.memory_service",
                new_callable=MagicMock,
            ),
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                # The graph must be a compiled LangGraph object
                assert graph is not None
                assert hasattr(graph, "ainvoke"), (
                    "build_comms_graph must return a compiled graph with ainvoke()"
                )
                assert hasattr(graph, "astream"), (
                    "build_comms_graph must return a compiled graph with astream()"
                )

    async def test_build_executor_graph_accepts_in_memory_checkpointer_flag(self):
        """build_executor_graph must compile with in_memory_checkpointer=True.

        If build_graph.py is deleted, this test fails immediately on import.
        """
        from app.agents.core.graph_builder.build_graph import build_executor_graph

        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="Executor agent response.")]
        )

        mock_registry = MagicMock()
        mock_registry.get_tool_dict.return_value = {}

        async def _dummy_retrieve_tools(query: str = "") -> list:
            """Stub retrieve tools coroutine (always returns empty list)."""
            return []

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new=AsyncMock(return_value=InMemoryStore()),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_dummy_retrieve_tools,
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                assert graph is not None
                assert hasattr(graph, "ainvoke"), (
                    "build_executor_graph must return a compiled graph with ainvoke()"
                )
