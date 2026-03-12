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
- LLM: FakeMessagesListChatModel
- store: InMemoryStore (no ChromaDB, no real tool indexing)
- Checkpointer: MemorySaver (no PostgreSQL)
- External API calls (memory service, tool registry): mocked via patch

DELETE ``app/agents/core/graph_builder/build_graph.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/utils.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from tests.helpers import BindableToolsFakeModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from app.override.langgraph_bigtool.utils import _replace_todos, dedupe_str_list
from tests.e2e.conftest import build_gaia_test_graph


@pytest.mark.e2e
class TestWorkflowExecution:
    """E2E tests for GAIA graph lifecycle and state schema correctness."""

    async def test_todos_channel_uses_replace_reducer(self):
        """The 'todos' channel must use last-write-wins (replace) semantics.

        _replace_todos is the reducer for the State.todos channel. When two
        successive updates arrive, the second list must completely replace the
        first — not merge or append to it.

        If _replace_todos is removed from utils.py or its semantics change,
        this test will fail.
        """
        first_todos = ["Buy milk", "Call dentist"]
        second_todos = ["Submit report"]

        result = _replace_todos(first_todos, second_todos)

        assert result == second_todos, (
            "_replace_todos must return the right-hand (newest) list, "
            "not the left-hand one or a merge of both."
        )
        assert "Buy milk" not in result, (
            "Previous todos must be fully replaced, not merged."
        )

    def test_selected_tool_ids_channel_deduplicates(self):
        """dedupe_str_list must remove duplicate tool IDs while preserving order.

        selected_tool_ids accumulates IDs across tool-retrieval turns. When the
        same ID appears multiple times, only the first occurrence must be kept.

        If dedupe_str_list is removed from utils.py, this test fails.
        """
        ids_with_duplicates = ["tool_a", "tool_b", "tool_a", "tool_c", "tool_b"]

        result = dedupe_str_list(ids_with_duplicates)

        assert result == ["tool_a", "tool_b", "tool_c"], (
            "dedupe_str_list must remove duplicates while preserving first-seen order."
        )
        assert len(result) == 3

    def test_messages_channel_accumulates(self):
        """The 'messages' channel must accumulate across successive updates.

        add_messages is the LangGraph reducer used by the messages channel in
        State (inherited from MessagesState). Applying it twice must grow the
        total message count — i.e., messages are appended, not replaced.

        This exercises the same accumulation contract relied on by the
        multi-turn checkpointing test below.
        """
        first_batch = [HumanMessage(content="Hello")]
        second_batch = [AIMessage(content="Hi there")]

        after_first = add_messages([], first_batch)
        after_second = add_messages(after_first, second_batch)

        assert len(after_second) == 2, (
            "add_messages must accumulate: two successive applications "
            "must produce a list with both messages."
        )
        assert after_second[0].content == "Hello"
        assert after_second[1].content == "Hi there"

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

        This tests GAIA's State schema + MemorySaver integration: the same
        thread_id must produce accumulated state (messages from turn 1 remain
        visible in turn 2) — the same pattern used by build_comms_graph in
        production. It is NOT a test of MemorySaver in isolation; it proves
        that the GAIA State channels (with their reducers) wire correctly with
        LangGraph's checkpointing mechanism.
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
        await graph.ainvoke(
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

        # Assert on specific message content to prove both turns were persisted
        contents = [m.content for m in accumulated]
        assert "First message" in contents, (
            "Turn-1 HumanMessage must be present in the accumulated checkpoint."
        )
        assert "Second message" in contents, (
            "Turn-2 HumanMessage must be present in the accumulated checkpoint."
        )
        assert "Response to first message." in contents, (
            "Turn-1 AIMessage must be present in the accumulated checkpoint."
        )
        assert "Response to second message." in contents, (
            "Turn-2 AIMessage must be present in the accumulated checkpoint."
        )

    async def test_different_thread_ids_have_independent_state(self, in_memory_store):
        """Separate thread_ids must not share state (thread isolation).

        This mirrors how the production comms agent handles concurrent users:
        each conversation thread is completely isolated.

        Each thread receives a unique sentinel phrase in its human message.
        After both graphs run, we assert:
        - Thread A's state contains only thread-A's sentinel (not thread B's).
        - Thread B's state contains only thread-B's sentinel (not thread A's).
        """
        checkpointer = MemorySaver()

        # Unique sentinel phrases that cannot appear in each other's thread
        sentinel_a = f"SENTINEL-ALPHA-{uuid4().hex}"
        sentinel_b = f"SENTINEL-BETA-{uuid4().hex}"

        fake_llm_a = BindableToolsFakeModel(
            responses=[AIMessage(content=f"Acknowledged: {sentinel_a}")]
        )
        fake_llm_b = BindableToolsFakeModel(
            responses=[AIMessage(content=f"Acknowledged: {sentinel_b}")]
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

        config_a = {
            "configurable": {"thread_id": "thread-alpha", "user_id": str(uuid4())}
        }
        config_b = {
            "configurable": {"thread_id": "thread-beta", "user_id": str(uuid4())}
        }

        await graph_a.ainvoke(
            {"messages": [HumanMessage(content=f"Message for alpha: {sentinel_a}")]},
            config=config_a,
        )
        await graph_b.ainvoke(
            {"messages": [HumanMessage(content=f"Message for beta: {sentinel_b}")]},
            config=config_b,
        )

        state_a = await graph_a.aget_state(config_a)
        state_b = await graph_b.aget_state(config_b)

        all_content_a = " ".join(m.content for m in state_a.values["messages"])
        all_content_b = " ".join(m.content for m in state_b.values["messages"])

        assert sentinel_a in all_content_a, (
            f"Thread A must contain its own sentinel phrase. Got: {all_content_a!r}"
        )
        assert sentinel_b not in all_content_a, (
            f"Thread A must NOT contain thread B's sentinel. Got: {all_content_a!r}"
        )
        assert sentinel_b in all_content_b, (
            f"Thread B must contain its own sentinel phrase. Got: {all_content_b!r}"
        )
        assert sentinel_a not in all_content_b, (
            f"Thread B must NOT contain thread A's sentinel. Got: {all_content_b!r}"
        )

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

        async def _noop_follow_up(state, config, store):  # NOSONAR — async required for LangGraph hook interface
            return state

        # Patch at the build_graph module namespace (where names are imported)
        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new_callable=AsyncMock,
                return_value=InMemoryStore(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_comms_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.follow_up_actions_node",
                new=_noop_follow_up,
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

                # Invoke the graph to prove it actually runs, not just compiles
                thread_id = str(uuid4())
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Hello from comms graph test")]},
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "user_id": str(uuid4()),
                        }
                    },
                )
                assert isinstance(result, dict), (
                    "ainvoke must return a dict of state values"
                )
                assert "messages" in result, (
                    "Comms graph result must contain 'messages' key"
                )

    async def test_build_executor_graph_accepts_in_memory_checkpointer_flag(self):
        """build_executor_graph must compile with in_memory_checkpointer=True.

        If build_graph.py is deleted, this test fails immediately on import.
        """
        import ast
        import inspect

        from app.agents.core.graph_builder.build_graph import build_executor_graph
        from app.agents.tools.todo_tools import TODO_TOOL_NAMES

        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="Executor agent response.")]
        )

        from langchain_core.tools import tool as lc_tool

        def _make_stub(name: str):
            async def _stub(input: str = "") -> str:  # noqa: A002
                return f"stub:{name}"

            _stub.__name__ = name
            _stub.__doc__ = f"Stub for {name}."
            return lc_tool(_stub)

        # Dynamically read initial_tool_ids from the real source so the mock
        # registry always provides stubs for every tool the graph expects.
        src = inspect.getsource(build_executor_graph)
        injected_by_graph = {"handoff"} | TODO_TOOL_NAMES
        idx = src.find("initial_tool_ids=")
        if idx != -1:
            bracket_start = src.index("[", idx)
            bracket_end = src.index("]", bracket_start) + 1
            raw_ids: list[str] = ast.literal_eval(src[bracket_start:bracket_end])
        else:
            raw_ids = []
        tool_dict = {
            tid: _make_stub(tid) for tid in raw_ids if tid not in injected_by_graph
        }

        mock_registry = MagicMock()
        mock_registry.get_tool_dict.return_value = tool_dict

        async def _fake_retrieve_tools(
            store, config, query=None, exact_tool_names=None
        ):
            """Minimal stub with proper signature for StructuredTool.from_function."""
            return {"tools_to_bind": [], "response": []}

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new_callable=AsyncMock,
                return_value=InMemoryStore(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.create_executor_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_fake_retrieve_tools,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                assert graph is not None
                assert hasattr(graph, "ainvoke"), (
                    "build_executor_graph must return a compiled graph with ainvoke()"
                )

                # Invoke the graph to prove it actually runs, not just compiles
                thread_id = str(uuid4())
                result = await graph.ainvoke(
                    {
                        "messages": [
                            HumanMessage(content="Hello from executor graph test")
                        ]
                    },
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "user_id": str(uuid4()),
                        }
                    },
                )
                assert isinstance(result, dict), (
                    "ainvoke must return a dict of state values"
                )
                assert "messages" in result, (
                    "Executor graph result must contain 'messages' key"
                )
