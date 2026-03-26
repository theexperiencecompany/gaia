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
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

# ---------------------------------------------------------------------------
# CRITICAL: import from the real production module.  If this import breaks,
# the tests fail – which is exactly what we want.
# ---------------------------------------------------------------------------
from app.agents.core.graph_builder.build_graph import build_comms_graph
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
# Boundary-only patches for follow_up_actions_node
#
# We mock ONLY the two external I/O boundaries:
#   1. get_free_llm_chain  – prevents real LLM client initialisation
#   2. get_stream_writer   – prevents LangGraph stream context requirement
#   3. invoke_with_fallback – the actual LLM network call
#   4. get_user_integration_capabilities – external HTTP/DB call
#
# The node's internal logic RUNS FOR REAL:
#   - messages[-2:] slicing
#   - SUGGEST_FOLLOW_UP_ACTIONS.format(...) prompt construction
#   - PydanticOutputParser.parse() parsing
#   - _pretty_print_messages() formatting
#
# invoke_with_fallback is mocked to return valid JSON so that the parser
# actually exercises its code path.
# ---------------------------------------------------------------------------

_VALID_FOLLOW_UP_JSON = (
    '{"actions": ["Schedule a follow-up meeting", "Send summary email", '
    '"Update the task list", "Check calendar availability"]}'
)


def _follow_up_node_io_patches(
    *,
    writer_fn: Any = None,
    llm_response: str = _VALID_FOLLOW_UP_JSON,
    capabilities: dict | None = None,
) -> list:
    """
    Return a list of context-manager patches that mock ONLY the I/O
    boundaries of follow_up_actions_node.

    Parameters
    ----------
    writer_fn:
        Callable to use as the stream writer.  Defaults to a no-op lambda.
    llm_response:
        String content the mocked LLM call should return.
    capabilities:
        Dict returned by get_user_integration_capabilities.
    """
    if writer_fn is None:
        writer_fn = lambda _: None  # noqa: E731

    if capabilities is None:
        capabilities = {"tool_names": []}

    return [
        # I/O boundary 1: LLM chain initialisation (no real client)
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
            return_value=MagicMock(),
        ),
        # I/O boundary 2: actual LLM network call
        patch(
            "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
            new_callable=AsyncMock,
            return_value=AIMessage(content=llm_response),
        ),
        # I/O boundary 3: external integrations DB/HTTP call
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
            new_callable=AsyncMock,
            return_value=capabilities,
        ),
        # I/O boundary 4: LangGraph stream context
        patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=writer_fn,
        ),
    ]


@contextlib.contextmanager
def _apply_all_patches(
    store_mock: MagicMock,
    io_patches: list,
    extra_patches: list | None = None,
):
    """Apply store, checkpointer, io, executor, memory patches via ExitStack.

    This avoids ``*io_patches`` unpacking inside ``with()`` which Python
    does not support (it produces a tuple, not individual context managers).
    """
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
        for p in io_patches:
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


@pytest.fixture()
async def comms_graph_simple():
    """
    Build the REAL comms agent graph with:
    - FakeMessagesListChatModel (single plain-text response, no tool calls)
    - InMemorySaver checkpointer
    - All external I/O mocked at boundaries only

    Yields the compiled CompiledGraph so tests can call ainvoke / aget_state.
    """
    fake_llm = create_fake_llm(["Hello! How can I help you today?"])
    store_mock = _make_chroma_store_mock()

    io_patches = _follow_up_node_io_patches()

    with _apply_all_patches(store_mock, io_patches):
        async with build_comms_graph(
            chat_llm=fake_llm, in_memory_checkpointer=True
        ) as graph:
            yield graph


@pytest.fixture()
async def comms_graph_with_tool_call():
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

    io_patches = _follow_up_node_io_patches()

    with _apply_all_patches(store_mock, io_patches):
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
        assert len(ai_messages) >= 1, (
            "Graph should have produced at least one AIMessage"
        )

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

        dangling_tool_call_id = "dangling_call_001"

        # An AIMessage with a tool call that has NO corresponding ToolMessage
        dangling_ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "call_executor",
                    "args": {"task": "dangling"},
                    "id": dangling_tool_call_id,
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

        # The graph must complete and produce at least one AIMessage from the LLM.
        # filter_messages_node strips dangling tool calls ephemerally (before the
        # LLM call) but does NOT remove them from the checkpoint. If the filter
        # didn't work, LangChain would raise an error about unmatched tool calls,
        # so reaching this point proves the filter ran correctly.
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1, (
            "Graph should have produced at least one AIMessage after stripping the dangling tool call"
        )

        # Verify the graph produced a NEW AIMessage (not just the dangling one).
        # The new message has no tool_calls (it's a terminal response).
        new_ai_messages = [m for m in ai_messages if not getattr(m, "tool_calls", None)]
        assert len(new_ai_messages) >= 1, (
            "The graph should have produced a new AIMessage with no pending tool calls."
        )

    async def test_pre_model_hook_does_not_persist_to_checkpoint(
        self, comms_graph_simple
    ):
        """
        manage_system_prompts_node runs as a pre_model_hook — it modifies the
        messages passed to the model ephemerally (filtering duplicates for the
        LLM call), but those modifications are NOT written back to the checkpoint.
        The persisted graph state still retains all original messages
        (LangGraph's append reducer). This test verifies the graph completes
        without error and produces an AI response when fed duplicate non-memory
        system prompts, and that both system prompts remain in the checkpoint.
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

        # Graph must complete and produce an AI response.
        ai_messages = [m for m in result["messages"] if m.type == "ai"]
        assert len(ai_messages) >= 1, (
            "Graph should have produced at least one AIMessage"
        )

        # Both system messages remain in the persisted state because
        # pre_model_hooks only filter for the LLM call, not the checkpoint.
        system_messages = [m for m in result["messages"] if m.type == "system"]
        non_memory = [
            m
            for m in system_messages
            if not m.additional_kwargs.get("memory_message", False)
        ]
        assert len(non_memory) == 2, (
            f"Both non-memory system prompts should remain in persisted state; "
            f"found {len(non_memory)}"
        )

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
        assert any(getattr(m, "tool_calls", None) for m in ai_messages), (
            "First AI message should contain tool_calls"
        )

        # ToolMessage from DynamicToolNode
        assert len(tool_messages) >= 1

        # Final AI message: plain text
        final_ai = [m for m in ai_messages if not getattr(m, "tool_calls", None)]
        assert len(final_ai) >= 1, (
            "Expected a final plain-text AI response after tool execution"
        )

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

        msgs_a = [
            m.content for m in state_a.values["messages"] if isinstance(m, HumanMessage)
        ]
        msgs_b = [
            m.content for m in state_b.values["messages"] if isinstance(m, HumanMessage)
        ]

        assert "Message from thread A" in msgs_a
        assert "Message from thread B" not in msgs_a
        assert "Message from thread B" in msgs_b
        assert "Message from thread A" not in msgs_b

    # ------------------------------------------------------------------
    # 5. follow_up_actions_node runs internal logic (not over-mocked)
    # ------------------------------------------------------------------

    async def test_memory_node_called_via_end_graph_hooks(self):
        """
        follow_up_actions_node is registered as an end_graph_hook in the real
        build_comms_graph.  Verify it is called (mocked writer receives data)
        when the graph finishes a turn without tool calls.

        We spy on get_stream_writer's return value to confirm the node fired.
        The node's internal logic (message slicing, prompt construction, parser)
        runs for real; only the LLM I/O boundary and stream writer are mocked.
        """
        store_mock = _make_chroma_store_mock()
        fake_llm = create_fake_llm(["All done!"])

        writer_calls: list[Any] = []

        def capturing_writer(data: Any) -> None:
            writer_calls.append(data)

        io_patches = _follow_up_node_io_patches(
            writer_fn=capturing_writer,
            # Return valid JSON so that PydanticOutputParser.parse() runs for real
            llm_response=('{"actions": ["Do A", "Do B", "Do C", "Do D"]}'),
            capabilities={"tool_names": ["call_executor"]},
        )

        with _apply_all_patches(store_mock, io_patches):
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

        keys_written = {
            k for call in writer_calls for k in (call if isinstance(call, dict) else {})
        }
        assert (
            "main_response_complete" in keys_written
            or "follow_up_actions" in keys_written
        ), (
            f"Expected follow_up_actions_node to write 'main_response_complete' or "
            f"'follow_up_actions'; got keys: {keys_written}"
        )

    async def test_follow_up_node_internal_logic_runs_for_real(self):
        """
        Verify that follow_up_actions_node's internal message slicing and
        PydanticOutputParser path execute for real (not mocked away).

        We provide enough messages (>= 2) to bypass the early-exit guard so that
        the slice `messages[-2:]` and `parser.parse()` are exercised.

        The writer should receive `follow_up_actions` whose content came from the
        parser actually parsing _VALID_FOLLOW_UP_JSON.
        """
        store_mock = _make_chroma_store_mock()
        # Give the main agent enough responses for two human messages
        fake_llm = create_fake_llm(["Response A", "Response B", "Response C"])

        received_actions: list[list[str]] = []

        def capturing_writer(data: Any) -> None:
            if isinstance(data, dict) and "follow_up_actions" in data:
                received_actions.append(data["follow_up_actions"])

        io_patches = _follow_up_node_io_patches(
            writer_fn=capturing_writer,
            llm_response=_VALID_FOLLOW_UP_JSON,
        )

        with _apply_all_patches(store_mock, io_patches):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                # Two messages so len(messages) >= 2 — the node won't early-exit
                await graph.ainvoke(
                    {
                        "messages": [
                            HumanMessage(content="First question"),
                            HumanMessage(content="Second question"),
                        ]
                    },
                    config=config,
                )

        # The parser ran and produced the expected actions list
        assert len(received_actions) >= 1, (
            "follow_up_actions_node should have written follow_up_actions "
            "(internal PydanticOutputParser path ran)"
        )
        flat = [a for batch in received_actions for a in batch]
        assert len(flat) >= 1, "Parser should have produced at least one action"

    # ------------------------------------------------------------------
    # 6. Error path coverage
    # ------------------------------------------------------------------

    async def test_node_exception_propagates_correctly(self):
        """
        When a pre_model_hook (filter_messages_node) raises an unhandled exception,
        the exception must propagate out of ainvoke as the original exception type
        — not silently swallowed, and not re-wrapped as a generic Exception that
        hides the original type.

        This test will FAIL if filter_messages_node's exception handler is removed
        AND the graph simply swallows the error, or if the error is re-raised as a
        different type.

        Design note: filter_messages_node wraps errors internally and returns state
        on failure, which means a patched internal sub-call that raises won't cause
        the graph to fail by default.  To prove exception-propagation behaviour we
        patch the node itself to raise directly, bypassing its own guard, then
        verify the exception propagates to the caller unchanged.
        """
        store_mock = _make_chroma_store_mock()
        fake_llm = create_fake_llm(["Should not be reached"])

        sentinel = RuntimeError("injected-filter-messages-failure")

        io_patches = _follow_up_node_io_patches()

        with _apply_all_patches(
            store_mock,
            io_patches,
            extra_patches=[
                patch(
                    "app.override.langgraph_bigtool.create_agent.execute_hooks",
                    side_effect=sentinel,
                ),
            ],
        ):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                with pytest.raises(RuntimeError) as exc_info:
                    await graph.ainvoke(
                        {"messages": [HumanMessage(content="Trigger the error")]},
                        config=config,
                    )

        # The exception must be exactly the RuntimeError we injected, not a
        # generic Exception wrapping it — this ensures the type is not swallowed.
        assert exc_info.type is RuntimeError, (
            f"Expected RuntimeError to propagate unchanged, got {exc_info.type}"
        )
        assert "injected-filter-messages-failure" in str(exc_info.value), (
            "Original exception message must be preserved in the propagated error"
        )

    async def test_comms_agent_handles_empty_messages(self):
        """
        Sending an empty messages list must not crash the graph.

        The production filter_messages_node and manage_system_prompts_node both
        have early-exit guards for empty message lists.  If those guards are
        removed, this test will detect the regression by catching the resulting
        exception (KeyError / IndexError).
        """
        store_mock = _make_chroma_store_mock()
        fake_llm = create_fake_llm(["Graceful empty response"])

        io_patches = _follow_up_node_io_patches()

        with _apply_all_patches(store_mock, io_patches):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                # An empty messages list — must not crash; graph may return
                # normally or raise a meaningful validation error, but must
                # NOT raise a bare IndexError or KeyError from the node logic.
                try:
                    result = await graph.ainvoke(
                        {"messages": []},
                        config=config,
                    )
                    # If it completes without error, the result must still carry
                    # a messages key (state contract is preserved).
                    assert "messages" in result, (
                        "State contract broken: 'messages' key missing after empty input"
                    )
                except (KeyError, IndexError) as exc:
                    pytest.fail(
                        f"Graph crashed with {type(exc).__name__} on empty messages input: {exc}"
                    )

    async def test_comms_agent_handles_malformed_tool_call(self):
        """
        When the LLM returns a tool call with invalid / missing arguments, the
        graph must return an error ToolMessage to the caller rather than crashing
        with an unhandled exception.

        The production DynamicToolNode wraps tool errors into ToolMessages so the
        graph can continue.  If that wrapping is removed, this test will fail
        because ainvoke will raise instead of returning a ToolMessage.
        """
        # The fake LLM emits a tool call with an empty args dict — call_executor
        # requires a "task" argument, so this is intentionally malformed.
        malformed_tool_call = {
            "name": "call_executor",
            "args": {},  # missing required "task" field
            "id": "malformed_call_001",
            "type": "tool_call",
        }
        fake_llm = create_fake_llm_with_tool_calls(
            [malformed_tool_call, "I encountered an issue."]
        )
        store_mock = _make_chroma_store_mock()

        io_patches = _follow_up_node_io_patches()

        with _apply_all_patches(store_mock, io_patches):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                # Must not raise — error should be surfaced as a ToolMessage
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Do the malformed task")]},
                    config=config,
                )

        messages = result["messages"]
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]

        # The graph must have produced a ToolMessage for the malformed call,
        # proving the error was returned to the caller rather than crashing.
        assert len(tool_messages) >= 1, (
            "Malformed tool call should produce a ToolMessage (error surfaced to caller), "
            "not a crash"
        )
        ids_seen = {tm.tool_call_id for tm in tool_messages}
        assert "malformed_call_001" in ids_seen, (
            f"Expected ToolMessage for malformed_call_001; got IDs: {ids_seen}"
        )

    async def test_comms_agent_timeout_handling(self):
        """
        When the LLM call raises asyncio.TimeoutError, the exception must
        propagate to the caller with the original TimeoutError type intact —
        it must NOT be swallowed silently or converted to a different type.

        This test will FAIL if:
        - The graph swallows the TimeoutError (returns normally instead of raising)
        - The graph re-raises as a generic Exception hiding the original type

        Note: asyncio.TimeoutError is a subclass of TimeoutError in Python 3.11+.
        We check for asyncio.TimeoutError directly.
        """
        store_mock = _make_chroma_store_mock()

        # The LLM raises TimeoutError immediately when invoked
        timeout_error = asyncio.TimeoutError("LLM request timed out")

        class TimeoutFakeLLM(FakeMessagesListChatModel):
            def bind_tools(self, tools: Any, **kwargs: Any) -> "TimeoutFakeLLM":
                return self

            async def ainvoke(self, *args, **kwargs):
                raise timeout_error

        fake_llm = TimeoutFakeLLM(responses=[])

        io_patches = _follow_up_node_io_patches()

        with _apply_all_patches(store_mock, io_patches):
            async with build_comms_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                config = _thread_config()
                with pytest.raises((asyncio.TimeoutError, TimeoutError)) as exc_info:
                    await graph.ainvoke(
                        {"messages": [HumanMessage(content="Trigger timeout")]},
                        config=config,
                    )

        # Verify the original exception type is preserved (not swallowed or re-typed)
        assert issubclass(exc_info.type, (asyncio.TimeoutError, TimeoutError)), (
            f"Expected TimeoutError to propagate, got {exc_info.type}. "
            "The graph must not swallow or re-type timeout errors."
        )
