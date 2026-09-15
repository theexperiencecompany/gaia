"""Integration tests for the GAIA comms agent flow patterns."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.constants.memory import ReconcileOutcome
from app.memory.ingestion import RetainedMemory
from app.models.memory_models import MemoryEntry
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread_config() -> dict:
    return {"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}}


def _make_chroma_store_mock() -> MagicMock:
    store = MagicMock()
    store.aget = AsyncMock(return_value=None)
    store.aput = AsyncMock(return_value=None)
    store.asearch = AsyncMock(return_value=[])
    store.alist_namespaces = AsyncMock(return_value=[])
    return store


def _make_memory_mock() -> MagicMock:
    """Create a memory_engine mock. Callers can hold a reference to assert on it.

    add_memory -> memory_engine.retain_single(...) -> RetainedMemory(entry, outcome);
    search_memory -> memory_engine.recall(...).
    """
    memory_mock = MagicMock()
    entry = MemoryEntry(id="mem-test-001", content="test memory", category_path="general")
    memory_mock.retain_single = AsyncMock(
        return_value=RetainedMemory(entry=entry, outcome=ReconcileOutcome.NEW)
    )
    memory_mock.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))
    return memory_mock


# Shared patches that prevent all external I/O; identical to test_real_comms_agent.py.
# Pass a pre-built memory_mock to assert on it after execution.
def _common_patches(store_mock, checkpointer_return=None, memory_mock=None):
    if memory_mock is None:
        memory_mock = _make_memory_mock()

    return [
        patch(
            "app.agents.tools.core.store.providers.aget",
            new_callable=AsyncMock,
            return_value=store_mock,
        ),
        patch(
            "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
            new_callable=AsyncMock,
            return_value=checkpointer_return,
        ),
        patch(
            "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
            new_callable=AsyncMock,
            return_value=FollowUpActions(actions=[]),
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
            "app.agents.core.background.executor_runner.prepare_executor_execution",
            new_callable=AsyncMock,
            return_value=(None, "executor not available in tests"),
        ),
        patch(
            "app.agents.tools.memory_tools.memory_engine",
            memory_mock,
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def comms_graph():
    """Real comms agent graph with a single plain-text fake LLM response."""
    fake_llm = create_fake_llm(["Hello! How can I help you today?"])
    store_mock = _make_chroma_store_mock()

    patches = _common_patches(store_mock)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
            yield graph


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCommsAgentFlow:
    """Flow tests for the production GAIA comms agent graph."""

    # ------------------------------------------------------------------
    # Graph structure
    # ------------------------------------------------------------------

    async def test_compiled_graph_has_required_nodes(self):
        """build_comms_graph must include agent, tools, and end_graph_hooks nodes."""
        fake_llm = create_fake_llm(["ok"])
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                # CompiledStateGraph exposes .nodes directly
                node_names = set(graph.nodes.keys())

        assert "agent" in node_names, (
            "'agent' node not found. build_comms_graph node wiring has changed."
        )
        assert "tools" in node_names, (
            "'tools' node not found. DynamicToolNode is not wired in comms graph."
        )
        assert "end_graph_hooks" in node_names, (
            "'end_graph_hooks' node not found. follow_up_actions_node is not wired."
        )

    async def test_comms_graph_tool_registry_includes_required_tools(self):
        """build_comms_graph must register call_executor, add_memory, search_memory."""
        tool_call = {
            "name": "search_memory",
            "args": {"query": "dark mode preference"},
            "id": "call_search_001",
            "type": "tool_call",
        }
        fake_llm = create_fake_llm_with_tool_calls([tool_call, "Found in memory."])
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                config = _thread_config()
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Do I prefer dark mode?")]},
                    config=config,
                )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "search_memory must be in the comms agent tool registry. "
            "No ToolMessage was produced — the tool is likely not registered."
        )

    # ------------------------------------------------------------------
    # Streaming interface
    # ------------------------------------------------------------------

    async def test_astream_yields_chunks(self):
        """build_comms_graph must support astream — the streaming interface used in production."""
        fake_llm = create_fake_llm(["Streaming response."])
        store_mock = _make_chroma_store_mock()
        chunks = []

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                async for chunk in graph.astream(
                    {"messages": [HumanMessage(content="Stream this")]},
                    config=_thread_config(),
                ):
                    chunks.append(chunk)

        assert len(chunks) > 0, (
            "astream must yield at least one chunk. "
            "If this fails, the comms graph is not streamable."
        )

        # Flatten all messages from every chunk dict (chunks are {node_name: state} dicts)
        all_messages = [
            msg
            for chunk in chunks
            for node_state in chunk.values()
            if isinstance(node_state, dict)
            for msg in node_state.get("messages", [])
        ]
        ai_messages = [m for m in all_messages if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, (
            "astream must yield at least one chunk containing an AIMessage. "
            "Routing logic may be broken if no AIMessage appears in any streamed chunk."
        )
        assert any("Streaming response." in (m.content or "") for m in ai_messages), (
            "Expected AIMessage with content 'Streaming response.' from the fake LLM. "
            f"Actual AI message contents: {[m.content for m in ai_messages]}"
        )

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    async def test_empty_message_content_does_not_crash(self, comms_graph):
        """Invoking the graph with an empty string message must not raise."""
        config = _thread_config()
        result = await comms_graph.ainvoke(
            {"messages": [HumanMessage(content="")]},
            config=config,
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, (
            "Graph must produce at least one AIMessage even for empty input."
        )
        # Verify the routing path was actually exercised, not silently short-circuited.
        # The comms_graph fixture programs the fake LLM to respond with this exact string.
        assert any("Hello! How can I help you today?" in (m.content or "") for m in ai_messages), (
            "Expected AIMessage with content 'Hello! How can I help you today?' from the "
            "fake LLM. If this fails, the agent node may have been bypassed or gutted. "
            f"Actual AI message contents: {[m.content for m in ai_messages]}"
        )

    async def test_minimal_invocation_no_system_message(self, comms_graph):
        """Invoking the graph with only a HumanMessage (no SystemMessage) must work."""
        config = _thread_config()
        result = await comms_graph.ainvoke(
            {"messages": [HumanMessage(content="Just a plain message.")]},
            config=config,
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1

    # ------------------------------------------------------------------
    # Multi-turn conversation
    # ------------------------------------------------------------------

    async def test_three_turn_conversation_accumulates_state(self):
        """Three sequential turns must accumulate messages via InMemorySaver."""
        from tests.helpers import BindableToolsFakeModel

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(content="Turn 1 reply."),
                AIMessage(content="Turn 2 reply."),
                AIMessage(content="Turn 3 reply."),
            ]
        )
        store_mock = _make_chroma_store_mock()

        patches = _common_patches(store_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                config = _thread_config()
                counts = []

                for i in range(1, 4):
                    await graph.ainvoke(
                        {"messages": [HumanMessage(content=f"Turn {i}")]},
                        config=config,
                    )
                    snap = await graph.aget_state(config)
                    counts.append(len(snap.values["messages"]))

        # Each turn adds at least 2 messages (HumanMessage + AIMessage)
        assert counts[0] < counts[1] < counts[2], (
            f"Message counts must grow across turns. Got: {counts}"
        )

        # Verify content from all turns is preserved — not just that count grew
        final_snap = await graph.aget_state(config)
        human_contents = [
            m.content for m in final_snap.values["messages"] if isinstance(m, HumanMessage)
        ]
        assert "Turn 1" in human_contents, (
            f"Turn 1 HumanMessage must survive into final state. Got: {human_contents}"
        )
        assert "Turn 2" in human_contents
        assert "Turn 3" in human_contents

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def test_add_memory_tool_call_executes_and_produces_tool_message(self):
        """When the LLM calls add_memory, a ToolMessage must appear and store_memory must be called."""
        tool_call = {
            "name": "add_memory",
            "args": {"content": "User likes dark mode", "category": "preference"},
            "id": "call_add_memory_001",
            "type": "tool_call",
        }
        fake_llm = create_fake_llm_with_tool_calls([tool_call, "Memory saved! Anything else?"])
        store_mock = _make_chroma_store_mock()

        # Hold a reference to memory_mock so we can assert on it after execution
        memory_mock = _make_memory_mock()
        patches = _common_patches(store_mock, memory_mock=memory_mock)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                # add_memory reads user_id from config["metadata"], not config["configurable"];
                # both keys must be present since LangGraph itself requires "configurable".
                user_id = str(uuid4())
                config = {
                    "configurable": {"thread_id": str(uuid4()), "user_id": user_id},
                    "metadata": {"user_id": user_id},
                }
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Remember that I like dark mode")]},
                    config=config,
                )

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1, (
            "add_memory tool call should produce a ToolMessage. "
            "If this fails, add_memory is not registered in the comms agent tool_registry."
        )
        assert tool_messages[0].tool_call_id == "call_add_memory_001"

        # Verify the tool actually called the memory engine — not just that it's registered.
        # If retain_single is never awaited, the most likely cause is that user_id was not
        # found in config["metadata"] (the key the tool actually reads).
        memory_mock.retain_single.assert_awaited_once()
        call_args_str = str(memory_mock.retain_single.call_args)
        assert "User likes dark mode" in call_args_str, (
            "retain_single must be called with content 'User likes dark mode'. "
            f"Actual call args: {call_args_str}"
        )
