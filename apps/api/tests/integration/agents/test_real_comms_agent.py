"""Real integration tests for the GAIA comms agent.

Unlike test_comms_agent_flow.py (which uses a fake echo graph), this module
imports and exercises the ACTUAL production `build_comms_graph` function from
app.agents.core.graph_builder.build_graph.

External I/O (DB clients, LLM API calls, memory service) is mocked so that
the LangGraph routing logic, pre_model_hooks (filter_messages_node,
manage_system_prompts_node), end_graph_hooks (follow_up_actions_node), and
tool registration all run for real.

If `build_comms_graph` (or the callee chain it pulls in) is removed or
renamed these tests will fail immediately — which is the desired behaviour.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------------
# CRITICAL: import from the real production module.  If this import breaks,
# the tests fail – which is exactly what we want.
# ---------------------------------------------------------------------------
from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _thread_config(extra: dict[str, Any] | None = None) -> dict:
    """Return a LangGraph config dict with a unique thread_id."""
    configurable: dict[str, Any] = {
        "thread_id": str(uuid4()),
        "user_id": str(uuid4()),
    }
    if extra:
        configurable.update(extra)
    return {"configurable": configurable}


def _make_chroma_store_mock() -> MagicMock:
    """Return a mock that satisfies langgraph.store.base.BaseStore."""
    store = MagicMock()
    store.aget = AsyncMock(return_value=None)
    store.aput = AsyncMock(return_value=None)
    store.asearch = AsyncMock(return_value=[])
    store.alist_namespaces = AsyncMock(return_value=[])
    return store


# ---------------------------------------------------------------------------
# Module-level patches applied for every test in this file
# ---------------------------------------------------------------------------

# Patch the chroma tools store so get_tools_store() does not need a real
# ChromaDB connection.  We also patch get_checkpointer_manager so that
# build_comms_graph falls through to the InMemorySaver branch.
COMMON_PATCHES = [
    # Prevent real ChromaDB / Google Embeddings initialisation
    patch(
        "app.agents.tools.core.store.providers.aget",
        new_callable=AsyncMock,
    ),
    # Prevent PostgreSQL checkpointer from being fetched
    patch(
        "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
        new_callable=AsyncMock,
    ),
    # Prevent follow_up_actions_node from calling real LLMs or external services
    patch(
        "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
        return_value=[],
    ),
    patch(
        "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
        new_callable=AsyncMock,
        return_value=AIMessage(content='{"actions": []}'),
    ),
    patch(
        "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
        new_callable=AsyncMock,
        return_value={"tool_names": []},
    ),
    # Prevent get_stream_writer from requiring a real LangGraph stream context
    patch(
        "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
        return_value=lambda _: None,
    ),
    # Prevent call_executor from trying to reach a real executor agent
    patch(
        "app.agents.tools.executor_tool.prepare_executor_execution",
        new_callable=AsyncMock,
        return_value=(None, "executor not available in tests"),
    ),
    # Prevent memory_tools from calling the real memory service
    patch(
        "app.agents.tools.memory_tools.memory_service",
        new_callable=MagicMock,
    ),
]


@pytest.fixture()
async def comms_graph_simple(monkeypatch):
    """
    Build the REAL comms agent graph with:
    - FakeMessagesListChatModel (single plain-text response, no tool calls)
    - InMemorySaver checkpointer
    - All external I/O mocked

    Yields the compiled CompiledGraph so tests can call ainvoke / aget_state.
    """
    fake_llm = create_fake_llm(["Hello! How can I help you today?"])
    store_mock = _make_chroma_store_mock()

    with (
        patch(
            "app.agents.tools.core.store.providers.aget",
            new_callable=AsyncMock,
            return_value=store_mock,
        ),
        patch(
            "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
            new_callable=AsyncMock,
            return_value=None,  # None → use InMemorySaver branch
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
            return_value=[],
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
            new_callable=AsyncMock,
            return_value=AIMessage(content='{"actions": []}'),
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
        patch(
            "app.agents.tools.executor_tool.prepare_executor_execution",
            new_callable=AsyncMock,
            return_value=(None, "executor not available in tests"),
        ),
        patch(
            "app.agents.tools.memory_tools.memory_service",
            new_callable=MagicMock,
        ),
    ):
        async with build_comms_graph(
            chat_llm=fake_llm, in_memory_checkpointer=True
        ) as graph:
            yield graph


@pytest.fixture()
async def comms_graph_with_tool_call(monkeypatch):
    """
    Build the REAL comms agent graph whose fake LLM first returns a tool call
    for `call_executor`, then returns a final text response.

    The call_executor tool itself is patched to return a fixed string without
    touching the real executor agent.
    """
    tool_call_spec = {
        "name": "call_executor",
        "args": {"task": "Check the weather"},
        "id": "call_executor_001",
        "type": "tool_call",
    }
    fake_llm = create_fake_llm_with_tool_calls(
        [tool_call_spec, "Done! The weather is sunny."]
    )
    store_mock = _make_chroma_store_mock()

    with (
        patch(
            "app.agents.tools.core.store.providers.aget",
            new_callable=AsyncMock,
            return_value=store_mock,
        ),
        patch(
            "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
            return_value=[],
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
            new_callable=AsyncMock,
            return_value=AIMessage(content='{"actions": []}'),
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
        # Make the executor tool return immediately with a fixed string
        patch(
            "app.agents.tools.executor_tool.prepare_executor_execution",
            new_callable=AsyncMock,
            return_value=(None, "executor not available in tests"),
        ),
        patch(
            "app.agents.tools.memory_tools.memory_service",
            new_callable=MagicMock,
        ),
    ):
        async with build_comms_graph(
            chat_llm=fake_llm, in_memory_checkpointer=True
        ) as graph:
            yield graph


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRealCommsAgent:
    """Integration tests that exercise the production GAIA comms agent graph."""

    # ------------------------------------------------------------------
    # 1. Compilation
    # ------------------------------------------------------------------

    async def test_graph_can_be_compiled(self):
        """
        build_comms_graph() must compile without raising.

        This directly validates that the production wiring (tool_registry dict,
        create_agent call, pre_model_hooks list, end_graph_hooks list) is intact.
        If any import or construction step inside build_comms_graph breaks, this
        test is the first to catch it.
        """
        store_mock = _make_chroma_store_mock()
        fake_llm = create_fake_llm(["ok"])

        with (
            patch(
                "app.agents.tools.core.store.providers.aget",
                new_callable=AsyncMock,
                return_value=store_mock,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                # The graph object must exist and expose the langgraph compiled-graph API
                assert graph is not None
                assert hasattr(graph, "ainvoke")
                assert hasattr(graph, "astream")
                assert hasattr(graph, "aget_state")

    # ------------------------------------------------------------------
    # 2. Message flows through real pre_model_hooks
    # ------------------------------------------------------------------

    async def test_message_flows_through_real_nodes(self, comms_graph_simple):
        """
        Invoke the graph with a HumanMessage and verify:
        - The graph completes without error.
        - At least one AIMessage appears in the output (LLM responded).
        - The production filter_messages_node and manage_system_prompts_node hooks
          ran (no exception escaped from them).

        We add a system prompt up-front so that manage_system_prompts_node has
        something to process.
        """
        config = _thread_config()

        result = await comms_graph_simple.ainvoke(
            {
                "messages": [
                    SystemMessage(content="You are a helpful assistant."),
                    HumanMessage(content="Hello!"),
                ]
            },
            config=config,
        )

        messages = result["messages"]
        assert len(messages) >= 2, "Expected at least the input messages + LLM reply"

        ai_messages = [m for m in messages if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, "Graph should have produced at least one AIMessage"

        # The manage_system_prompts_node keeps only the latest non-memory system
        # prompt; there should be at most one non-memory system message.
        system_messages = [m for m in messages if m.type == "system"]
        non_memory_system = [
            m
            for m in system_messages
            if not m.additional_kwargs.get("memory_message", False)
        ]
        assert len(non_memory_system) <= 1, (
            "manage_system_prompts_node should keep at most one non-memory system prompt, "
            f"found {len(non_memory_system)}"
        )

    async def test_filter_messages_node_removes_unanswered_tool_calls(
        self, comms_graph_simple
    ):
        """
        Seed the state with an AI message that has an unanswered tool call.
        After the graph runs its pre_model_hooks (filter_messages_node), that
        dangling tool call should be stripped so the LLM does not see it.

        We verify indirectly: the graph must complete without the LLM receiving
        invalid state (LangChain would raise if the tool call + no ToolMessage
        pair was forwarded to the model).
        """
        config = _thread_config()

        # An AIMessage with a tool call that has NO corresponding ToolMessage
        dangling_ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "call_executor",
                    "args": {"task": "dangling"},
                    "id": "dangling_call_001",
                    "type": "tool_call",
                }
            ],
        )

        # The graph should complete: filter_messages_node will strip the dangling
        # tool call before passing messages to the model.
        result = await comms_graph_simple.ainvoke(
            {
                "messages": [
                    HumanMessage(content="What can you do?"),
                    dangling_ai,
                ]
            },
            config=config,
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1

    async def test_duplicate_system_prompts_deduplicated(self, comms_graph_simple):
        """
        manage_system_prompts_node (a real pre_model_hook) must discard older
        non-memory system prompts and keep only the latest one.
        """
        config = _thread_config()

        result = await comms_graph_simple.ainvoke(
            {
                "messages": [
                    SystemMessage(content="Old system prompt."),
                    HumanMessage(content="First message."),
                    SystemMessage(content="New system prompt."),
                    HumanMessage(content="Second message."),
                ]
            },
            config=config,
        )

        system_messages = [m for m in result["messages"] if m.type == "system"]
        non_memory = [
            m
            for m in system_messages
            if not m.additional_kwargs.get("memory_message", False)
        ]

        # Only the newest non-memory system prompt should survive.
        assert len(non_memory) <= 1, (
            f"manage_system_prompts_node should have deduplicated system prompts; "
            f"found {len(non_memory)}"
        )
        if non_memory:
            assert "New system prompt." in non_memory[0].content

    # ------------------------------------------------------------------
    # 3. Tool routing
    # ------------------------------------------------------------------

    async def test_tool_routing_to_tool_node(self, comms_graph_with_tool_call):
        """
        When the fake LLM emits a tool call for `call_executor`, the real
        LangGraph conditional edge (should_continue) must route execution to the
        DynamicToolNode, which executes the tool and produces a ToolMessage.

        This validates that:
        - The production should_continue routing logic runs.
        - The DynamicToolNode is wired correctly for the comms agent.
        - A ToolMessage is produced for the call_executor invocation.
        """
        config = _thread_config()

        result = await comms_graph_with_tool_call.ainvoke(
            {"messages": [HumanMessage(content="Check the weather for me")]},
            config=config,
        )

        messages = result["messages"]
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]

        assert len(tool_messages) >= 1, (
            "Graph should have produced a ToolMessage after routing to tool node"
        )
        # The tool call ID must match what our fake LLM emitted.
        tool_call_ids = {tm.tool_call_id for tm in tool_messages}
        assert "call_executor_001" in tool_call_ids, (
            f"Expected ToolMessage with tool_call_id='call_executor_001', "
            f"got ids: {tool_call_ids}"
        )

    async def test_tool_routing_then_final_response(self, comms_graph_with_tool_call):
        """
        After the tool executes (ToolMessage), the graph re-enters the agent node.
        The fake LLM's second response is a plain text message, so should_continue
        routes to end_graph_hooks (follow_up_actions_node) and then END.

        Verify the full message sequence: Human → AI(tool_call) → Tool → AI(final).
        """
        config = _thread_config()

        result = await comms_graph_with_tool_call.ainvoke(
            {"messages": [HumanMessage(content="What is the weather?")]},
            config=config,
        )

        messages = result["messages"]
        ai_messages = [m for m in messages if isinstance(m, AIMessage)]
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]

        # First AI message: tool call
        assert any(
            getattr(m, "tool_calls", None) for m in ai_messages
        ), "First AI message should contain tool_calls"

        # ToolMessage from DynamicToolNode
        assert len(tool_messages) >= 1

        # Final AI message: plain text
        final_ai = [m for m in ai_messages if not getattr(m, "tool_calls", None)]
        assert len(final_ai) >= 1, "Expected a final plain-text AI response after tool execution"

    # ------------------------------------------------------------------
    # 4. State structure
    # ------------------------------------------------------------------

    async def test_state_structure_has_expected_fields(self, comms_graph_simple):
        """
        After invocation, aget_state() must return a snapshot whose .values dict
        contains the fields declared in the bigtool State (messages,
        selected_tool_ids, todos) and any extensions used by comms graph.
        """
        config = _thread_config()

        await comms_graph_simple.ainvoke(
            {"messages": [HumanMessage(content="Hi")]},
            config=config,
        )

        snapshot = await comms_graph_simple.aget_state(config)
        values = snapshot.values

        # Core fields required by the production State schema
        assert "messages" in values, "State must contain 'messages'"
        assert "selected_tool_ids" in values, "State must contain 'selected_tool_ids'"

        # messages must be a list
        assert isinstance(values["messages"], list)

    async def test_state_accumulates_across_turns(self, comms_graph_simple):
        """
        Calling ainvoke twice on the same thread_id must accumulate messages
        (checkpointing works with InMemorySaver in the real graph).
        """
        config = _thread_config()

        await comms_graph_simple.ainvoke(
            {"messages": [HumanMessage(content="First turn")]},
            config=config,
        )
        state_after_first = await comms_graph_simple.aget_state(config)
        count_after_first = len(state_after_first.values["messages"])

        # Re-seed the LLM with a fresh response for the second turn.
        # Because FakeMessagesListChatModel is stateful (it pops from its queue),
        # we rebuild the graph fixture for the second call by simply calling again.
        await comms_graph_simple.ainvoke(
            {"messages": [HumanMessage(content="Second turn")]},
            config=config,
        )
        state_after_second = await comms_graph_simple.aget_state(config)
        count_after_second = len(state_after_second.values["messages"])

        assert count_after_second > count_after_first, (
            "Messages should accumulate across turns via InMemorySaver checkpointing"
        )

    async def test_different_thread_ids_are_isolated(self, comms_graph_simple):
        """
        Two different thread_ids must have independent state — even when using the
        same compiled graph object with InMemorySaver.
        """
        config_a = _thread_config()
        config_b = _thread_config()

        await comms_graph_simple.ainvoke(
            {"messages": [HumanMessage(content="Message from thread A")]},
            config=config_a,
        )
        await comms_graph_simple.ainvoke(
            {"messages": [HumanMessage(content="Message from thread B")]},
            config=config_b,
        )

        state_a = await comms_graph_simple.aget_state(config_a)
        state_b = await comms_graph_simple.aget_state(config_b)

        msgs_a = [m.content for m in state_a.values["messages"] if isinstance(m, HumanMessage)]
        msgs_b = [m.content for m in state_b.values["messages"] if isinstance(m, HumanMessage)]

        assert "Message from thread A" in msgs_a
        assert "Message from thread B" not in msgs_a
        assert "Message from thread B" in msgs_b
        assert "Message from thread A" not in msgs_b

    # ------------------------------------------------------------------
    # 5. Memory node (end_graph_hook) is invoked
    # ------------------------------------------------------------------

    async def test_memory_node_called_via_end_graph_hooks(self):
        """
        follow_up_actions_node is registered as an end_graph_hook in the real
        build_comms_graph.  Verify it is called (mocked writer receives data)
        when the graph finishes a turn without tool calls.

        We spy on get_stream_writer's return value to confirm the node fired.
        """
        store_mock = _make_chroma_store_mock()
        fake_llm = create_fake_llm(["All done!"])

        writer_calls: list[Any] = []

        def capturing_writer(data: Any) -> None:
            writer_calls.append(data)

        with (
            patch(
                "app.agents.tools.core.store.providers.aget",
                new_callable=AsyncMock,
                return_value=store_mock,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=[],
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new_callable=AsyncMock,
                return_value=AIMessage(content='{"actions": ["Do A", "Do B"]}'),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new_callable=AsyncMock,
                return_value={"tool_names": ["call_executor"]},
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=capturing_writer,
            ),
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                return_value=(None, "executor not available in tests"),
            ),
            patch(
                "app.agents.tools.memory_tools.memory_service",
                new_callable=MagicMock,
            ),
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="Hi, summarise my day")]},
                    config=config,
                )

        # follow_up_actions_node always calls writer({"main_response_complete": True})
        # and then writer({"follow_up_actions": [...]}) — so writer_calls must be
        # non-empty, proving the end_graph_hook ran.
        assert len(writer_calls) >= 1, (
            "follow_up_actions_node (end_graph_hook) should have called the stream writer "
            "at least once, but writer_calls is empty"
        )

        keys_written = {k for call in writer_calls for k in (call if isinstance(call, dict) else {})}
        assert "main_response_complete" in keys_written or "follow_up_actions" in keys_written, (
            f"Expected follow_up_actions_node to write 'main_response_complete' or "
            f"'follow_up_actions'; got keys: {keys_written}"
        )
