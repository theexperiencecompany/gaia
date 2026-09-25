"""Unit tests for subagent_runner.py and subagent_helpers.py."""

from contextlib import contextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.types import Command, Interrupt
from prometheus_client import REGISTRY
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import PromptSlot
from app.agents.context.tiers import AgentTier
from app.agents.core.background import redis_writer as rw
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import RunKind, StreamSession, create_session
from app.agents.core.background.subagent_channel import SubagentCancel
from app.agents.core.graph_manager import GraphUnavailableError
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
    ThreadSeed,
    _consume_stream_event,
    _finalize_run,
    _process_updates_payload,
    _StreamRun,
    build_initial_messages,
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.llm.lane import AgentRole
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.hil import LANGGRAPH_INTERRUPT_KEY
from app.constants.llm import DEV_MODEL_OPTIONS, EXECUTOR_RECURSION_LIMIT
from app.helpers.agent_helpers import AgentIdentity, AgentLane, AgentThread
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from tests._harness.context_chain import slots_of

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subagent_config(agent_name: str = "github_agent") -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name=agent_name,
        tool_space="github_space",
        domain="github",
        capabilities="github stuff",
        use_cases="github use",
        system_prompt="You are the GitHub agent.",
    )


def _make_subagent(
    subagent_id: str = "github",
    short_name: str | None = "gh",
    agent_name: str = "github_agent",
    provider: str = "github",
    managed_by: str = "composio",
) -> Subagent:
    """Create a real Subagent instance for tests."""
    return Subagent(
        id=subagent_id,
        name=subagent_id.title(),
        provider=provider,
        managed_by=managed_by,  # type: ignore[arg-type]  # fixture uses a plain string for the managed_by Literal
        config=_make_subagent_config(agent_name=agent_name),
        short_name=short_name,
    )


def _make_ctx(**overrides) -> SubagentExecutionContext:
    defaults: dict[str, object] = {
        "subagent_graph": AsyncMock(),
        "agent_name": "test_agent",
        "config": {"configurable": {"thread_id": "t1"}},
        "configurable": {"thread_id": "t1"},
        "integration_id": "test",
        "initial_state": {"messages": [], "todos": []},
        "user_id": "u1",
        "stream_id": None,
    }
    defaults.update(overrides)
    return SubagentExecutionContext(**defaults)  # type: ignore[arg-type]  # fixture spreads an untyped defaults dict into the model


def _make_run(**overrides) -> _StreamRun:
    """One in-flight execute_subagent_stream drive, without the stream.

    The per-mode handlers and the finalizer all take this by reference, so a
    test can drive them directly instead of through the astream loop.
    """
    defaults: dict[str, object] = {
        "ctx": _make_ctx(),
        "stream_writer": None,
        "integration_metadata": None,
        "subagent_id": None,
    }
    ctx_overrides = overrides.pop("ctx_overrides", None)
    if ctx_overrides is not None:
        defaults["ctx"] = _make_ctx(**ctx_overrides)
    defaults.update(overrides)
    return _StreamRun(**defaults)  # type: ignore[arg-type]  # fixture spreads an untyped defaults dict


def _mcp_subagent(subagent_id: str, *, requires_auth: bool) -> Subagent:
    return Subagent(
        id=subagent_id,
        name=subagent_id,
        provider=subagent_id,
        managed_by="mcp",
        config=_make_subagent_config(agent_name=f"{subagent_id}_agent"),
        mcp_config=MCPConfig(server_url="https://mcp.test", requires_auth=requires_auth),
    )


FAKE_SUBAGENTS = (
    _make_subagent("github", "gh", "github_agent", "github"),
    _make_subagent("gmail", "gmail", "gmail_agent", "gmail"),
)


def _make_integration(
    integration_id: str = "github",
    short_name: str = "gh",
    has_subagent: bool = True,
    agent_name: str = "github_agent",
    provider: str = "github",
) -> MagicMock:
    """Subagent-shaped fixture for get_subagent_by_id, mirroring the Subagent dataclass surface."""
    subagent_cfg = MagicMock()
    subagent_cfg.has_subagent = has_subagent
    subagent_cfg.agent_name = agent_name
    subagent_cfg.system_prompt = "You are the GitHub agent."

    subagent = MagicMock()
    subagent.id = integration_id
    subagent.name = integration_id.title()
    subagent.short_name = short_name
    subagent.provider = provider
    subagent.config = subagent_cfg
    return subagent


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------


class TestBuildInitialMessages:
    """Canonical slot order: [static, dynamic_stable, memory_recall?, human_task, time]."""

    @staticmethod
    def _assembled(volatile: SystemMessage | None = None) -> Any:
        return patch(
            "app.agents.core.subagents.subagent_runner.assemble_context",
            new_callable=AsyncMock,
            return_value=AssembledContext(
                stable=SystemMessage(
                    content="Context", additional_kwargs={"dynamic_context": True}
                ),
                volatile=volatile,
            ),
        )

    @pytest.mark.asyncio
    async def test_seed_is_static_then_stable_then_task_then_clock(self):
        sys_msg = SystemMessage(content="System prompt")

        with self._assembled():
            result = await build_initial_messages(
                system_message=sys_msg,
                agent_name="test_agent",
                task="Do the thing",
                seed=ThreadSeed(
                    tier=AgentTier.EXECUTOR, configurable={"user_timezone": "Asia/Kolkata"}
                ),
            )

        assert slots_of(result) == [
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.CONVERSATION,
            PromptSlot.TIME,
        ]
        assert result[0] is sys_msg
        assert result[2].content == "Do the thing"

    @pytest.mark.asyncio
    async def test_volatile_content_is_slotted_before_the_conversation(self):
        """It has to stay inside the leading system block — Gemini drops a system message following a non-system one."""
        volatile = SystemMessage(content="recall", additional_kwargs={"memory_recall": True})

        with self._assembled(volatile=volatile):
            result = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="task",
                seed=ThreadSeed(tier=AgentTier.EXECUTOR, configurable={}),
            )

        assert slots_of(result) == [
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.MEMORY_RECALL,
            PromptSlot.CONVERSATION,
            PromptSlot.TIME,
        ]

    @pytest.mark.asyncio
    async def test_clock_is_last_and_is_not_a_system_message(self):
        with self._assembled():
            result = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="task",
                seed=ThreadSeed(
                    tier=AgentTier.EXECUTOR, configurable={"user_timezone": "Asia/Kolkata"}
                ),
            )

        assert isinstance(result[-1], HumanMessage)
        assert result[-1].additional_kwargs.get("time_context") is True

    @pytest.mark.asyncio
    async def test_human_message_has_visible_to(self):
        with self._assembled():
            result = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="my_agent",
                task="task",
                seed=ThreadSeed(tier=AgentTier.EXECUTOR, configurable={}),
            )

        human_msg = next(m for m in result if m.type == "human" and m.content == "task")
        assert "my_agent" in human_msg.additional_kwargs["visible_to"]

    @pytest.mark.asyncio
    async def test_retrieval_query_defaults_to_task(self):
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="my search query",
                seed=ThreadSeed(tier=AgentTier.EXECUTOR, configurable={}),
            )

        assert mock_assemble.call_args.args[0].query == "my search query"

    @pytest.mark.asyncio
    async def test_retrieval_query_overrides_an_enhanced_task(self):
        """The executor injects routing hints into the task text; retrieving against those pollutes the search."""
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="enhanced task with hints",
                seed=ThreadSeed(
                    tier=AgentTier.EXECUTOR, configurable={}, retrieval_query="original query"
                ),
            )

        assert mock_assemble.call_args.args[0].query == "original query"

    @pytest.mark.asyncio
    async def test_the_comms_request_reaches_the_assembler_beside_the_retrieval_query(self):
        """Recall reuses what comms fetched for the user's own words; losing them re-recalls on the brief."""
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="enhanced task with hints",
                seed=ThreadSeed(
                    tier=AgentTier.EXECUTOR,
                    configurable={},
                    retrieval_query="book the usual table",
                    request_query="can you book our usual table for Friday?",
                ),
            )

        ctx = mock_assemble.call_args.args[0]
        assert ctx.request_query == "can you book our usual table for Friday?"
        assert ctx.query == "book the usual table"

    @pytest.mark.asyncio
    async def test_tier_and_ids_reach_the_assembler(self):
        """The tier selects which sections apply; the wrong one silently loses provider metadata."""
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                task="task",
                seed=ThreadSeed(
                    tier=AgentTier.PROVIDER_SUBAGENT,
                    configurable={},
                    user_id="uid-1",
                    subagent_id="github_agent",
                    integration_id="github",
                ),
            )

        ctx = mock_assemble.call_args.args[0]
        assert ctx.tier is AgentTier.PROVIDER_SUBAGENT
        assert ctx.user_id == "uid-1"
        assert ctx.subagent_id == "github_agent"
        assert ctx.integration_id == "github"


# ---------------------------------------------------------------------------
# execute_subagent_stream
# ---------------------------------------------------------------------------


class TestExecuteSubagentStream:
    @pytest.mark.asyncio
    async def test_accumulates_ai_content(self):
        chunk1 = AIMessageChunk(content="Hello ")
        chunk2 = AIMessageChunk(content="world")
        tool_msg = ToolMessage(content="done", tool_call_id="tc-acc")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk1, {}))
            yield ("messages", (chunk2, {}))
            yield ("messages", (tool_msg, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream

        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert not result.paused
        assert result.text == "Hello world"

    @pytest.mark.asyncio
    async def test_silent_messages_skipped(self):
        chunk = AIMessageChunk(content="should skip")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk, {"silent": True}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert not result.paused
        assert result.text == "Task completed"  # default when no content

    @pytest.mark.asyncio
    async def test_empty_message_returns_default(self):
        async def _fake_astream(*args, **kwargs):
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert not result.paused
        assert result.text == "Task completed"

    @pytest.mark.asyncio
    async def test_tool_message_emits_tool_output(self):
        tool_msg = ToolMessage(content="tool result data", tool_call_id="tc-1")
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (tool_msg, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        stream_writer.assert_called_once()
        call_data = stream_writer.call_args[0][0]
        assert "tool_output" in call_data
        assert call_data["tool_output"]["tool_call_id"] == "tc-1"

    @pytest.mark.asyncio
    async def test_tool_message_content_not_truncated(self):
        """tool_output streams the full content without truncation."""
        long_content = "x" * 5000
        tool_msg = ToolMessage(content=long_content, tool_call_id="tc-2")
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (tool_msg, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        output = stream_writer.call_args[0][0]["tool_output"]["output"]
        assert output == long_content

    @pytest.mark.asyncio
    async def test_run_messages_capture_the_agents_tool_calls_and_their_results(self):
        """The outcome carries this run's tool-bearing messages: the agent's AIMessages plus their ToolMessages."""
        ai = AIMessage(
            content="",
            tool_calls=[
                {"name": "GMAIL_FETCH_MESSAGES", "args": {"max_messages": 5}, "id": "tc-1"}
            ],
        )
        tool_msg = ToolMessage(content="ok", tool_call_id="tc-1")

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [ai]}})
            yield ("messages", (tool_msg, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            # The SSE tool-card formatting is not under test — and unpatched it
            # reaches the real tool registry provider.
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await execute_subagent_stream(ctx)

        assert result.run_messages == (ai, tool_msg)

    @pytest.mark.asyncio
    async def test_run_messages_skip_non_agent_node_updates(self):
        """Pre-model hooks replay historical AIMessages; those must not leak stale tool calls into the record."""
        stale = AIMessage(
            content="",
            tool_calls=[{"name": "OLD_TOOL", "args": {}, "id": "tc-old"}],
        )

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"filter_messages_node": {"messages": [stale]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert result.run_messages == ()

    @pytest.mark.asyncio
    async def test_updates_emit_tool_data(self):
        """Updates stream mode should extract tool entries and emit them."""
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": []}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[("tc-1", tool_entry)],
            ),
        ):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        stream_writer.assert_called_once()
        call_data = stream_writer.call_args[0][0]
        assert call_data["tool_data"] == tool_entry

    @pytest.mark.asyncio
    async def test_non_agent_node_updates_skipped(self):
        """Without this guard, a replayed checkpoint re-emits stale tool_calls, duplicating tools in the UI."""
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            # Simulate pre-model hook nodes replaying historical messages
            yield ("updates", {"filter_messages_node": {"messages": []}})
            yield ("updates", {"manage_system_prompts_node": {"messages": []}})
            # Only the "agent" node should produce tool_data
            yield ("updates", {"agent": {"messages": []}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        call_count = 0

        def _extract_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            return [("tc-1", tool_entry)]

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                side_effect=_extract_side_effect,
            ),
        ):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        # extract_tool_entries_from_update should only be called once (for "agent" node)
        assert call_count == 1
        stream_writer.assert_called_once()
        call_data = stream_writer.call_args[0][0]
        assert call_data["tool_data"] == tool_entry

    @pytest.mark.asyncio
    async def test_custom_events_forwarded(self):
        custom_payload = {"progress": "50%"}
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("custom", custom_payload)

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        stream_writer.assert_called_once_with(custom_payload)

    @pytest.mark.asyncio
    async def test_no_stream_writer_no_errors(self):
        """When stream_writer is None, tool data and custom events are silently skipped."""
        tool_msg = ToolMessage(content="result", tool_call_id="tc-1")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (tool_msg, {}))
            yield ("custom", {"progress": "done"})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx, stream_writer=None)

        # Should not raise
        assert not result.paused
        assert result.text == "Task completed"

    @pytest.mark.asyncio
    async def test_cancellation_breaks_stream(self):
        chunk1 = AIMessageChunk(content="First ")
        chunk2 = AIMessageChunk(content="Second")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk1, {}))
            yield ("messages", (chunk2, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph, stream_id="s-1")

        # is_cancelled returns False first, then True
        cancel_calls = [False, True]

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                side_effect=cancel_calls,
            ),
        ):
            result = await execute_subagent_stream(ctx)

        # Only first chunk was accumulated before cancellation broke the loop.
        # When no tool ran the runner wraps the content in a diagnostic message;
        # verify "First " appears and "Second" does not (cancellation succeeded).
        assert "First " in result.text
        assert "Second" not in result.text

    async def test_executor_cancel_stops_the_stream_with_a_cancelled_result(self):
        """A targeted executor cancel (its flag raised) stops the subagent at the next superstep and returns a SUBAGENT_CANCELLED result, so the executor learns it stopped rather than reading a silent partial."""

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": []}})
            yield ("messages", (AIMessageChunk(content="should not reach"), {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph, stream_id="s-1")

        fake_cancel = MagicMock()
        fake_cancel.is_requested = AsyncMock(return_value=True)
        fake_cancel.clear = AsyncMock()

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.SubagentCancel",
                return_value=fake_cancel,
            ),
        ):
            result = await execute_subagent_stream(ctx)

        assert "<subagent_cancelled>" in result.text
        assert "should not reach" not in result.text
        fake_cancel.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_tuple_events_skipped(self):
        """Events with length != 2 should be silently skipped."""

        async def _fake_astream(*args, **kwargs):
            yield ("a", "b", "c")  # 3-tuple, should be skipped
            yield ("messages", (AIMessageChunk(content="ok"), {}))
            yield ("messages", (ToolMessage(content="done", tool_call_id="tc-skip"), {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert not result.paused
        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_integration_metadata_passed_to_extract(self):
        metadata = {"icon_url": "https://icon.png", "name": "Custom MCP"}

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": []}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_extract,
        ):
            await execute_subagent_stream(ctx, integration_metadata=metadata)

        call_kwargs = mock_extract.call_args.kwargs
        assert call_kwargs["integration_metadata"] is metadata

    @pytest.mark.asyncio
    async def test_the_runs_subagent_id_tags_everything_it_emits(self):
        """The id the caller passes nests every event in the subagent's row; dropped, it renders outside it."""
        tool_msg = ToolMessage(content="result", tool_call_id="tc-sub")
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (tool_msg, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=stream_writer, subagent_id="sub-1")

        assert stream_writer.call_args[0][0]["tool_output"]["subagent_id"] == "sub-1"


# ---------------------------------------------------------------------------
# _process_updates_payload — driven directly, one payload at a time
# ---------------------------------------------------------------------------


class TestProcessUpdatesPayload:
    """The "updates" branch, called directly."""

    @staticmethod
    def _entries(entries: list[tuple[str, dict[str, Any]]]) -> Any:
        return patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=entries,
        )

    @pytest.mark.asyncio
    async def test_an_interrupt_event_records_its_payloads_and_stops_there(self):
        """Approval values accumulate because one __interrupt__ event arrives per paused task."""
        run = _make_run()
        payload = {LANGGRAPH_INTERRUPT_KEY: ({"approval_id": "a1"}, {"approval_id": "a2"})}

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await _process_updates_payload(run, payload)

        assert run.pending_approvals == [{"approval_id": "a1"}, {"approval_id": "a2"}]
        assert run.run_messages == []

    @pytest.mark.asyncio
    async def test_a_non_agent_node_is_skipped_without_abandoning_the_rest(self):
        """Skipping the pre-model hook must continue, not break, since the agent node's update follows in the SAME payload."""
        ai = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "tc-1"}])
        writer = MagicMock()
        run = _make_run(stream_writer=writer)
        payload = {
            "filter_messages_node": {"messages": []},
            "agent": {"messages": [ai]},
        }

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            self._entries([("tc-1", {"name": "web_search"})]),
        ):
            await _process_updates_payload(run, payload)

        assert run.run_messages == [ai]
        writer.assert_called_once_with({"tool_data": {"name": "web_search"}})

    @pytest.mark.asyncio
    async def test_an_agent_update_without_messages_records_nothing(self):
        """The default is an empty list, not None — a node update with no messages at all is ordinary."""
        run = _make_run()

        with patch("app.agents.core.subagents.subagent_runner.log"), self._entries([]):
            await _process_updates_payload(run, {"agent": {"todos": []}})

        assert run.run_messages == []

    @pytest.mark.asyncio
    async def test_only_tool_bearing_messages_are_captured(self):
        """The filter reads tool_calls defensively: some messages in an update carry no such attribute at all."""
        ai = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "tc-1"}])
        plain = HumanMessage(content="not a tool call")
        run = _make_run()

        with patch("app.agents.core.subagents.subagent_runner.log"), self._entries([]):
            await _process_updates_payload(run, {"agent": {"messages": [plain, ai]}})

        assert run.run_messages == [ai]

    @pytest.mark.asyncio
    async def test_the_extractor_receives_this_nodes_update_and_the_runs_own_state(self):
        metadata = {"icon_url": "https://icon.png"}
        run = _make_run(integration_metadata=metadata)
        run.emitted_tool_calls.add("tc-already")
        state_update = {"messages": []}

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            self._entries([]) as mock_extract,
        ):
            await _process_updates_payload(run, {"agent": state_update})

        assert mock_extract.call_args.args == ()
        assert mock_extract.call_args.kwargs == {
            "state_update": state_update,
            "emitted_tool_calls": {"tc-already"},
            "integration_metadata": metadata,
        }

    @pytest.mark.asyncio
    async def test_announcing_a_call_claims_its_result_for_this_stream_and_subagent(self):
        """note_tool_output_owner stops "messages" mode re-emitting the same ToolMessage untagged."""
        run = _make_run(subagent_id="sub-1", ctx_overrides={"stream_id": "s-1"})

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch("app.agents.core.subagents.subagent_runner.note_tool_output_owner") as mock_note,
            self._entries([("tc-1", {"name": "web_search"})]),
        ):
            await _process_updates_payload(run, {"agent": {"messages": []}})

        assert mock_note.call_args_list == [call("s-1", "tc-1", "sub-1")]

    @pytest.mark.asyncio
    async def test_a_run_with_no_stream_id_claims_against_the_empty_string(self):
        run = _make_run(subagent_id="sub-1", ctx_overrides={"stream_id": None})

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch("app.agents.core.subagents.subagent_runner.note_tool_output_owner") as mock_note,
            self._entries([("tc-1", {"name": "web_search"})]),
        ):
            await _process_updates_payload(run, {"agent": {"messages": []}})

        assert mock_note.call_args_list == [call("", "tc-1", "sub-1")]

    @pytest.mark.asyncio
    async def test_a_subagents_tool_data_carries_its_id_beside_the_entry(self):
        writer = MagicMock()
        run = _make_run(stream_writer=writer, subagent_id="sub-1")
        tool_entry = {"name": "web_search", "args": {"q": "test"}}

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            self._entries([("tc-1", tool_entry)]),
        ):
            await _process_updates_payload(run, {"agent": {"messages": []}})

        assert writer.call_args_list == [
            call({"tool_data": {**tool_entry, "subagent_id": "sub-1"}})
        ]
        # The entry itself is never mutated in place — the tagged copy is a new dict.
        assert tool_entry == {"name": "web_search", "args": {"q": "test"}}

    @pytest.mark.asyncio
    async def test_without_a_subagent_id_the_entry_is_written_untagged(self):
        writer = MagicMock()
        run = _make_run(stream_writer=writer, subagent_id=None)
        tool_entry = {"name": "web_search", "args": {"q": "test"}}

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            self._entries([("tc-1", tool_entry)]),
        ):
            await _process_updates_payload(run, {"agent": {"messages": []}})

        assert writer.call_args_list == [call({"tool_data": tool_entry})]


# ---------------------------------------------------------------------------
# _consume_stream_event — the per-mode dispatch
# ---------------------------------------------------------------------------


class TestConsumeStreamEvent:
    """The "messages" branch hands five positional arguments down, each deciding where the chunk's output is routed."""

    @staticmethod
    def _messages_handler() -> Any:
        return patch(
            "app.agents.core.subagents.subagent_runner._process_messages_payload",
            return_value="accumulated",
        )

    @pytest.mark.asyncio
    async def test_the_messages_handler_gets_the_runs_writer_id_and_stream(self):
        writer = MagicMock()
        run = _make_run(
            stream_writer=writer, subagent_id="sub-1", ctx_overrides={"stream_id": "s-1"}
        )
        run.complete_message = "so far"
        payload = (AIMessageChunk(content="hi"), {})

        with self._messages_handler() as mock_handler:
            await _consume_stream_event(run, "messages", payload)

        assert mock_handler.call_args == call(payload, "so far", writer, "sub-1", "s-1")
        assert run.complete_message == "accumulated"

    @pytest.mark.asyncio
    async def test_a_run_with_no_stream_id_passes_the_empty_string_down(self):
        run = _make_run(ctx_overrides={"stream_id": None})
        payload = (AIMessageChunk(content="hi"), {})

        with self._messages_handler() as mock_handler:
            await _consume_stream_event(run, "messages", payload)

        assert mock_handler.call_args.args[4] == ""


# ---------------------------------------------------------------------------
# _finalize_run
# ---------------------------------------------------------------------------


_NARRATION = (
    "The test_agent subagent ended without running any tool; it only produced "
    'planning text: "I will send the email". Re-issue the handoff with an '
    "explicit instruction to perform the action."
)


class TestFinalizeRun:
    """What a drained (or paused) run turns into, and the wide-event fields the outcome is stamped with."""

    @staticmethod
    def _ctx_overrides() -> dict[str, object]:
        return {
            "initial_state": {
                "messages": [HumanMessage(content="a"), HumanMessage(content="b")],
                "todos": [],
            }
        }

    def test_a_paused_run_returns_its_partial_text_the_merged_approval_and_its_messages(self):
        ai = AIMessage(content="", tool_calls=[{"name": "send_email", "args": {}, "id": "tc-1"}])
        run = _make_run()
        run.complete_message = "partial"
        run.run_messages = [ai]
        run.pending_approvals = [
            {"approval_id": "a1", "tool": "send_email"},
            {"approval_id": "a2", "tool": "delete_file"},
        ]

        with patch("app.agents.core.subagents.subagent_runner.log"):
            outcome = _finalize_run(run)

        assert outcome.paused
        assert outcome.text == "partial"
        assert outcome.interrupt == {
            "approval_id": "a1",
            "tool": "send_email",
            "approval_ids": ["a1", "a2"],
        }
        assert outcome.run_messages == (ai,)

    def test_a_narration_only_run_is_reported_as_an_actionable_failure(self):
        run = _make_run(ctx_overrides=self._ctx_overrides())
        run.complete_message = "I will send the email"

        with patch("app.agents.core.subagents.subagent_runner.log") as mock_log:
            outcome = _finalize_run(run)

        assert outcome.text == _NARRATION
        assert not outcome.paused
        assert mock_log.warning.call_args == call(
            "subagent_returned_narration_only", subagent_name="test_agent"
        )
        assert mock_log.set.call_args == call(
            subagent={
                "name": "test_agent",
                "provider": "test",
                "response_length": len(_NARRATION),
                "messages_count": 2,
            }
        )

    def test_the_executors_plain_answer_is_its_answer(self):
        """A collection run's whole job is to report what landed, in words; nothing re-issues the executor."""
        run = _make_run(ctx_overrides={**self._ctx_overrides(), "integration_id": "executor"})
        run.complete_message = "The report is drafted and saved."

        with patch("app.agents.core.subagents.subagent_runner.log"):
            outcome = _finalize_run(run)

        assert outcome.text == "The report is drafted and saved."

    def test_an_announced_tool_call_makes_the_same_text_an_ordinary_result(self):
        """A run that announced a call did the work, even if no ToolMessage came back before the stream ended."""
        run = _make_run(ctx_overrides=self._ctx_overrides())
        run.complete_message = "I will send the email"
        run.emitted_tool_calls.add("tc-1")

        with patch("app.agents.core.subagents.subagent_runner.log") as mock_log:
            outcome = _finalize_run(run)

        assert outcome.text == "I will send the email"
        mock_log.warning.assert_not_called()
        assert mock_log.set.call_args == call(
            subagent={
                "name": "test_agent",
                "provider": "test",
                "response_length": len("I will send the email"),
                "messages_count": 2,
            }
        )


# ---------------------------------------------------------------------------
# prepare_executor_execution
# ---------------------------------------------------------------------------


class TestPrepareExecutorExecution:
    @pytest.fixture(autouse=True)
    def _mock_uploaded_files(self):
        # prepare_executor_execution surfaces conversation uploads via
        # FileService.list_conversation_files (a Motor query). Unit tests must
        # not touch the DB, so stub it out for the whole class.
        with patch(
            "app.agents.core.subagents.subagent_runner.FileService.list_conversation_files",
            new_callable=AsyncMock,
            return_value=[],
        ):
            yield

    def _prepare_patches(self, build_config, graph=None):
        """Everything prepare_executor_execution reaches outside itself."""
        return (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=graph if graph is not None else MagicMock(name="executor_graph"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                build_config,
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="executor sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_the_executors_config_is_built_from_the_conversation_it_belongs_to(self):
        """The executor gets its OWN config, derived from comms's; every argument here is load-bearing."""
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        configurable = {
            "user_id": "u1",
            "thread_id": "t1",
            "email": "t@t.com",
            "user_name": "Test",
        }
        graph, config, system, context = self._prepare_patches(build_config)
        with graph, config, system, context:
            await prepare_executor_execution(task="run tests", configurable=configurable)

        assert build_config.call_args.args == ()
        # Dataclass equality, so this stays exactly as strict as the flat-kwargs
        # dict it replaced: every field of every group has to match.
        assert build_config.call_args.kwargs == {
            "identity": AgentIdentity(
                conversation_id="t1",
                user={"user_id": "u1", "email": "t@t.com", "name": "Test"},
                agent_name="executor_agent",
            ),
            "lane": AgentLane(role=AgentRole.EXECUTOR, dev_option=None),
            "thread": AgentThread(
                thread_id="executor_t1",
                base_configurable=configurable,
                subagent_id="executor_agent",
                vfs_session_id="t1",
                recursion_limit=EXECUTOR_RECURSION_LIMIT,
            ),
        }

    @pytest.mark.asyncio
    async def test_the_users_own_request_rides_to_the_executors_context_with_the_bare_task(self):
        """The executor recalls on the message comms already recalled on, and on the unenhanced task."""
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        graph, config, system, context = self._prepare_patches(build_config)
        with graph, config, system, context as mock_assemble:
            await prepare_executor_execution(
                task="book the usual table",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "email": "t@t.com",
                    "user_name": "Test",
                    "user_request": "can you book our usual table for Friday?",
                },
            )

        ctx = mock_assemble.call_args.args[0]
        assert ctx.request_query == "can you book our usual table for Friday?"
        assert ctx.query == "book the usual table"

    @pytest.mark.asyncio
    async def test_the_dev_executor_model_comms_stashed_becomes_this_runs_dev_option(self):
        """DEV-ONLY: without this the executor silently inherits comms's lane and the header's picker does nothing."""
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        graph, config, system, context = self._prepare_patches(build_config)
        with graph, config, system, context:
            await prepare_executor_execution(
                task="run tests",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "email": "t@t.com",
                    "user_name": "Test",
                    "dev_executor_model": "minimax-m3",
                },
            )

        assert build_config.call_args.kwargs["lane"].dev_option == DEV_MODEL_OPTIONS["minimax-m3"]

    @pytest.mark.asyncio
    async def test_an_unknown_stashed_id_selects_no_dev_option(self):
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        graph, config, system, context = self._prepare_patches(build_config)
        with graph, config, system, context:
            await prepare_executor_execution(
                task="run tests",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "email": "t@t.com",
                    "user_name": "Test",
                    "dev_executor_model": "no-such-model",
                },
            )

        assert build_config.call_args.kwargs["lane"].dev_option is None

    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="executor sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
        ):
            ctx, error = await prepare_executor_execution(
                task="run tests",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "email": "t@t.com",
                    "user_name": "Test",
                },
            )

        assert error is None
        assert ctx is not None
        assert ctx.agent_name == "executor_agent"
        assert ctx.integration_id == "executor"
        assert ctx.subagent_graph is mock_graph
        # A fresh executor run starts with no todos carried over from the last one.
        assert ctx.initial_state["todos"] == []

    @pytest.mark.asyncio
    async def test_executor_graph_unavailable(self):
        with patch(
            "app.agents.core.graph_manager.GraphManager.get_graph",
            new_callable=AsyncMock,
            side_effect=GraphUnavailableError("executor_agent", "provider failed in test"),
        ):
            ctx, error = await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
            )

        assert ctx is None
        assert "not available" in error

    @pytest.mark.asyncio
    async def test_direct_handoff_hint_injected(self):
        """When tool_category matches a known subagent, a hint is injected."""
        mock_graph = MagicMock(name="executor_graph")
        github = _make_subagent("github", "gh", "github_agent", "github")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="executor sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
        ):
            ctx, error = await prepare_executor_execution(
                task="search repos",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "tool_category": "github",
                    "selected_tool": "github_search_repos",
                },
            )

        assert error is None
        # Found by slot, not position: the clock now trails the task, so an
        # index-based lookup would silently read the wrong message.
        task_msg = next(
            m
            for m in ctx.initial_state["messages"]
            if m.type == "human" and not m.additional_kwargs.get("time_context")
        )
        assert "DIRECT EXECUTION HINT" in task_msg.content
        assert 'activate_integration(integration_id="github")' in task_msg.content
        assert "handoff(" not in task_msg.content

    @pytest.mark.asyncio
    async def test_no_hint_without_tool_category(self):
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="executor sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
        ):
            ctx, error = await prepare_executor_execution(
                task="plain task",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                },
            )

        human_msg = ctx.initial_state["messages"][-1]
        assert "DIRECT EXECUTION HINT" not in human_msg.content

    @pytest.mark.asyncio
    async def test_stream_id_propagated(self):
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
        ):
            ctx, error = await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                stream_id="my-stream-id",
            )

        assert ctx.stream_id == "my-stream-id"

    @pytest.mark.asyncio
    async def test_vfs_session_id_fallback_to_thread_id(self):
        """When vfs_session_id is not in configurable, thread_id is used."""
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ) as mock_build_config,
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
        ):
            await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
            )

        call_kwargs = mock_build_config.call_args.kwargs
        assert call_kwargs["thread"].vfs_session_id == "t1"

    @pytest.mark.asyncio
    async def test_the_seed_carries_the_tier_the_user_and_the_unenhanced_query(self):
        """The query must stay the ORIGINAL task; the workflow section injected into enhanced_task would pollute the search."""
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        graph, config, system, context = self._prepare_patches(build_config)
        with graph, config, system, context as mock_assemble:
            ctx, error = await prepare_executor_execution(
                task="run tests",
                configurable={"user_id": "u1", "thread_id": "t1", "workflow_id": "wf-1"},
            )

        assert error is None
        seed_ctx = mock_assemble.call_args.args[0]
        assert seed_ctx.tier is AgentTier.EXECUTOR
        assert seed_ctx.user_id == "u1"
        assert seed_ctx.query == "run tests"

        task_msg = next(
            m
            for m in ctx.initial_state["messages"]
            if m.type == "human" and not m.additional_kwargs.get("time_context")
        )
        # The seeded turn is the enhanced text, addressed to the executor by name.
        assert task_msg.additional_kwargs["visible_to"] == {"executor_agent"}
        assert task_msg.content.startswith("run tests\n")
        assert task_msg.content != "run tests"

    async def _task_for_category(self, tool_category: str, *known: Subagent) -> str:
        """Prepare an executor run for the category; return its task message text."""
        registry = {subagent.id: subagent for subagent in known}
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "executor_t1"}})
        get_graph, build, system, assemble = self._prepare_patches(build_config)
        with (
            get_graph,
            build,
            system,
            assemble,
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                side_effect=registry.get,
            ),
        ):
            ctx, _ = await prepare_executor_execution(
                task="find the roadmap page",
                configurable={"user_id": "u1", "thread_id": "t1", "tool_category": tool_category},
            )
        assert ctx is not None
        return next(
            str(m.content)
            for m in ctx.initial_state["messages"]
            if m.type == "human" and not m.additional_kwargs.get("time_context")
        )

    async def test_an_unknown_category_gets_no_hint(self):
        task = await self._task_for_category("nope", _make_subagent("github"))

        assert task == "find the roadmap page"

    async def test_a_per_user_mcp_category_is_handed_off(self):
        notion = _mcp_subagent("notion-mcp", requires_auth=True)

        task = await self._task_for_category("notion-mcp", notion)

        assert task == (
            "find the roadmap page\n\n"
            "DIRECT EXECUTION HINT: This request should be handled by 'notion-mcp'. "
            "Skip retrieve_tools discovery and directly "
            'handoff(subagent_id="notion-mcp", task="...") with the full request, then '
            "use its result for the user's request."
        )

    async def test_an_mcp_category_needing_no_sign_in_is_activated_in_context(self):
        docs = _mcp_subagent("docs-mcp", requires_auth=False)

        task = await self._task_for_category("docs-mcp", docs)

        assert 'activate_integration(integration_id="docs-mcp")' in task
        assert "handoff(" not in task


# ---------------------------------------------------------------------------
# subagent_helpers.py — build_subagent_system_prompt
# ---------------------------------------------------------------------------


from app.agents.core.subagents.subagent_helpers import (
    build_subagent_system_prompt,
    create_subagent_system_message,
)


class TestBuildSubagentSystemPrompt:
    @pytest.mark.asyncio
    async def test_returns_static_base_prompt_without_user_metadata(self):
        """The static subagent prompt must be byte-identical across users; provider metadata is a separate message."""
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.context.fetchers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"Username": "testuser"},
            ) as mock_meta,
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await build_subagent_system_prompt("github")

        assert "You are the GitHub agent." in result
        assert "USER CONTEXT FOR GITHUB" not in result
        assert "testuser" not in result
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integration_not_found_uses_custom_prompt(self):
        from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT

        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ):
            result = await build_subagent_system_prompt("custom_tool_123")

        assert result == CUSTOM_MCP_SUBAGENT_PROMPT

    @pytest.mark.asyncio
    async def test_integration_not_found_prefers_base_system_prompt(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ):
            result = await build_subagent_system_prompt(
                "custom_tool_123", base_system_prompt="Explicit override"
            )

        assert result == "Explicit override"

    @pytest.mark.asyncio
    async def test_base_system_prompt_override(self):
        integration = _make_integration("github")

        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=integration,
        ):
            result = await build_subagent_system_prompt(
                "github", base_system_prompt="Custom prompt"
            )

        assert result == "Custom prompt"

    @pytest.mark.asyncio
    async def test_blank_integration_id_returns_empty(self):
        with patch("app.agents.core.subagents.subagent_helpers.log"):
            assert await build_subagent_system_prompt("") == ""


# ---------------------------------------------------------------------------
# create_subagent_system_message
# ---------------------------------------------------------------------------


class TestCreateSubagentSystemMessage:
    @pytest.mark.asyncio
    async def test_returns_system_message(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.build_subagent_system_prompt",
            new_callable=AsyncMock,
            return_value="Test prompt",
        ):
            result = await create_subagent_system_message(integration_id="github")

        assert isinstance(result, SystemMessage)
        assert result.content == "Test prompt"


# ---------------------------------------------------------------------------
# reasoning: streamed per delta, persisted per block
# ---------------------------------------------------------------------------


def _thinking(text: str) -> AIMessageChunk:
    return AIMessageChunk(content="", additional_kwargs={"reasoning_content": text})


@contextmanager
def _real_stream_writer(stream_id: str = "s-reasoning"):
    """Drive the run through the REAL redis stream writer over a live session.

    The split under test lives between the publish and the collector, so a
    MagicMock writer cannot see it: the SSE frames and the persisted entries have
    to come off the same run.
    """
    session = create_session(stream_id, RunKind.QUEUED)
    with patch.object(rw, "stream_manager") as stream_manager:
        stream_manager.publish_chunk = AsyncMock()
        yield make_redis_stream_writer(stream_id), stream_manager, session


def _published_reasoning(stream_manager: MagicMock) -> list[str]:
    frames = [
        json.loads(call[0][1].removeprefix("data: "))
        for call in stream_manager.publish_chunk.call_args_list
    ]
    return [frame["reasoning"]["content"] for frame in frames if "reasoning" in frame]


def _collected_reasoning(session: StreamSession) -> list[str]:
    return [evt["reasoning"]["content"] for evt in session.tool_events if "reasoning" in evt]


class TestReasoningStreamsPerDeltaButPersistsPerBlock:
    """The live stream stays token by token, but the SAVE coalesces each contiguous run of thinking into one entry.

    One prod conversation ended up carrying ~22k reasoning entries when saved
    per token instead.
    """

    @pytest.mark.asyncio
    async def test_four_deltas_stream_as_four_frames_and_persist_as_two_entries(self):
        with _real_stream_writer() as (writer, stream_manager, session):

            async def _fake_astream(*args, **kwargs):
                yield ("messages", (_thinking("a"), {}))
                yield ("messages", (_thinking("b"), {}))
                yield ("messages", (_thinking("c"), {}))
                yield ("updates", {"agent": {"messages": []}})
                yield ("messages", (_thinking("d"), {}))

            mock_graph = MagicMock()
            mock_graph.astream = _fake_astream
            ctx = _make_ctx(subagent_graph=mock_graph)

            with (
                patch("app.agents.core.subagents.subagent_runner.log"),
                patch(
                    "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                    new_callable=AsyncMock,
                    return_value=[("tc-1", {"name": "web_search"})],
                ),
            ):
                await execute_subagent_stream(ctx, stream_writer=writer)

            # Liveness: every delta reached the client, in order.
            assert _published_reasoning(stream_manager) == ["a", "b", "c", "d"]
            # Persistence: the tool call is the only boundary, so two blocks.
            assert _collected_reasoning(session) == ["abc", "d"]

    @pytest.mark.asyncio
    async def test_the_entries_that_reach_tool_data_are_two_as_well(self):
        """What is persisted is the DRAINED shape; the entry count has to survive absorb_collector_event too."""
        with _real_stream_writer() as (writer, _stream_manager, _session):

            async def _fake_astream(*args, **kwargs):
                yield ("messages", (_thinking("a"), {}))
                yield ("messages", (_thinking("b"), {}))
                yield ("messages", (_thinking("c"), {}))
                yield ("updates", {"agent": {"messages": []}})
                yield ("messages", (_thinking("d"), {}))

            mock_graph = MagicMock()
            mock_graph.astream = _fake_astream
            ctx = _make_ctx(subagent_graph=mock_graph)

            with (
                patch("app.agents.core.subagents.subagent_runner.log"),
                patch(
                    "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                    new_callable=AsyncMock,
                    return_value=[("tc-1", {"name": "web_search"})],
                ),
            ):
                await execute_subagent_stream(ctx, stream_writer=writer)

            reasoning_entries = [
                entry["data"]["reasoning"]
                for entry in drain_executor_tool_data("s-reasoning")
                if entry.get("tool_category") == "reasoning"
            ]

        assert reasoning_entries == ["abc", "d"]

    @pytest.mark.asyncio
    async def test_thinking_with_no_tool_after_it_is_one_entry_not_dropped(self):
        with _real_stream_writer() as (writer, stream_manager, session):

            async def _fake_astream(*args, **kwargs):
                yield ("messages", (_thinking("no tool "), {}))
                yield ("messages", (_thinking("followed this"), {}))

            mock_graph = MagicMock()
            mock_graph.astream = _fake_astream
            ctx = _make_ctx(subagent_graph=mock_graph)

            with patch("app.agents.core.subagents.subagent_runner.log"):
                await execute_subagent_stream(ctx, stream_writer=writer)

            assert _published_reasoning(stream_manager) == ["no tool ", "followed this"]
            assert _collected_reasoning(session) == ["no tool followed this"]

    @pytest.mark.asyncio
    async def test_a_run_that_parks_on_an_approval_keeps_its_thinking(self):
        with _real_stream_writer() as (writer, _stream_manager, session):

            async def _fake_astream(*args, **kwargs):
                yield ("messages", (_thinking("this one "), {}))
                yield ("messages", (_thinking("needs a human"), {}))
                yield ("updates", {"__interrupt__": ()})

            mock_graph = MagicMock()
            mock_graph.astream = _fake_astream
            ctx = _make_ctx(subagent_graph=mock_graph)

            with patch("app.agents.core.subagents.subagent_runner.log"):
                await execute_subagent_stream(ctx, stream_writer=writer)

            assert _collected_reasoning(session) == ["this one needs a human"]

    @pytest.mark.asyncio
    async def test_two_subagents_thinking_on_one_stream_never_merge(self):
        """Merging on adjacency alone would splice one subagent's thinking into another's block."""
        with _real_stream_writer() as (writer, _stream_manager, session):
            writer({"reasoning": {"content": "alpha ", "subagent_id": "sub-1"}})
            writer({"reasoning": {"content": "beta", "subagent_id": "sub-2"}})
            writer({"reasoning": {"content": " more", "subagent_id": "sub-2"}})

            assert _collected_reasoning(session) == ["alpha ", "beta more"]


# ---------------------------------------------------------------------------
# latency: one active span per segment
# ---------------------------------------------------------------------------


def _subagent_count(integration_id: str, status: str) -> float:
    # The span labels the registry integration id, never the per-call row uuid.
    return (
        REGISTRY.get_sample_value(
            "subagent_run_seconds_count", {"subagent_id": integration_id, "status": status}
        )
        or 0.0
    )


def _subagent_sum(integration_id: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "subagent_run_seconds_sum", {"subagent_id": integration_id, "status": status}
        )
        or 0.0
    )


class _FakeClock:
    """A time stub standing in for subagent_runner.time, one tick per call."""

    def __init__(self, *values: float) -> None:
        self._values = list(values)

    def perf_counter(self) -> float:
        return self._values.pop(0)


class TestSubagentRunLatency:
    @pytest.mark.asyncio
    async def test_finished_segment_observes_success_span(self):
        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)
        before = _subagent_count("test", "success")

        with patch("app.agents.core.subagents.subagent_runner.log"):
            outcome = await execute_subagent_stream(
                ctx, stream_writer=MagicMock(), subagent_id="lat-sub"
            )

        assert outcome.text
        assert not outcome.paused
        assert _subagent_count("test", "success") == before + 1

    @pytest.mark.asyncio
    async def test_per_call_row_id_never_becomes_a_series(self):
        """The span carries the registry integration id, not the per-call UI row uuid."""

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(
                ctx, stream_writer=MagicMock(), subagent_id="row-uuid-per-call-1"
            )

        assert (
            REGISTRY.get_sample_value(
                "subagent_run_seconds_count",
                {"subagent_id": "row-uuid-per-call-1", "status": "success"},
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_paused_segment_observes_paused_span_not_success(self):
        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": []}})
            if False:
                yield ("updates", {})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)
        paused_before = _subagent_count("test", "paused")
        success_before = _subagent_count("test", "success")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner._finalize_run",
                return_value=SubagentOutcome(text="", interrupt={"approval_id": "a1"}),
            ),
        ):
            outcome = await execute_subagent_stream(
                ctx, stream_writer=MagicMock(), subagent_id="lat-sub-paused"
            )

        assert outcome.paused
        assert _subagent_count("test", "paused") == paused_before + 1
        assert _subagent_count("test", "success") == success_before

    @pytest.mark.asyncio
    async def test_failed_segment_observes_error_span(self):
        async def _fake_astream(*args, **kwargs):
            raise RuntimeError("graph exploded")
            yield ("updates", {})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)
        before = _subagent_count("test", "error")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            pytest.raises(RuntimeError, match="graph exploded"),
        ):
            await execute_subagent_stream(ctx, stream_writer=MagicMock(), subagent_id="lat-sub-err")

        assert _subagent_count("test", "error") == before + 1

    @pytest.mark.asyncio
    async def test_stream_is_driven_with_seed_state_config_and_exit_durability(self):
        """Pins the seed state, the three stream modes, the run config and durability="exit"."""
        captured: dict[str, Any] = {}

        async def _fake_astream(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=MagicMock())

        assert captured["args"] == (ctx.initial_state,)
        assert captured["kwargs"]["stream_mode"] == ["messages", "custom", "updates"]
        assert captured["kwargs"]["config"] is ctx.config
        assert captured["kwargs"]["durability"] == "exit"

    @pytest.mark.asyncio
    async def test_resume_reclocks_the_run_before_streaming_it(self):
        """A resume goes through _with_current_time(resume, configurable), in that argument order."""
        captured: dict[str, Any] = {}
        reclocker = MagicMock(return_value=object())

        async def _fake_astream(*args, **kwargs):
            captured["args"] = args
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=("x",), next=None))
        ctx = _make_ctx(subagent_graph=mock_graph)
        resume = Command(resume="approved")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner._with_current_time",
                reclocker,
            ),
        ):
            await execute_subagent_stream(ctx, resume=resume)

        reclocker.assert_called_once_with(resume, ctx.configurable)
        assert captured["args"][0] is reclocker.return_value

    @pytest.mark.asyncio
    async def test_custom_mcp_label_collapses_to_one_series(self):
        """A custom MCP integration's user-created name collapses to the literal "custom_mcp"."""

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(
            subagent_graph=mock_graph,
            agent_name="custom_mcp_google",
            integration_id="google",
        )
        before = _subagent_count("custom_mcp", "success")

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(ctx, stream_writer=MagicMock())

        assert _subagent_count("custom_mcp", "success") == before + 1

    @pytest.mark.asyncio
    async def test_label_falls_back_integration_id_then_agent_name_then_unknown(self):
        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream

        agent_ctx = _make_ctx(subagent_graph=mock_graph, agent_name="test_agent", integration_id="")
        agent_before = _subagent_count("test_agent", "success")
        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(agent_ctx, stream_writer=MagicMock())
        assert _subagent_count("test_agent", "success") == agent_before + 1

        unknown_ctx = _make_ctx(subagent_graph=mock_graph, agent_name="", integration_id="")
        unknown_before = _subagent_count("unknown", "success")
        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(unknown_ctx, stream_writer=MagicMock())
        assert _subagent_count("unknown", "success") == unknown_before + 1

    @pytest.mark.asyncio
    async def test_cancelled_segment_observes_cancelled_span_not_success(self):
        async def _fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="partial"), {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph, stream_id="s-cancel")
        cancelled_before = _subagent_count("test", "cancelled")
        success_before = _subagent_count("test", "success")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_is_cancelled,
        ):
            outcome = await execute_subagent_stream(
                ctx, stream_writer=MagicMock(), subagent_id="lat-cancel"
            )

        assert not outcome.paused
        mock_is_cancelled.assert_awaited_once_with("s-cancel")
        assert _subagent_count("test", "cancelled") == cancelled_before + 1
        assert _subagent_count("test", "success") == success_before

    @pytest.mark.asyncio
    async def test_success_span_records_elapsed_seconds_not_the_summed_clock(self):
        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)
        before = _subagent_sum("test", "success")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.time",
                new=_FakeClock(100.0, 100.25),
            ),
        ):
            await execute_subagent_stream(ctx, stream_writer=MagicMock(), subagent_id="lat-clock")

        assert _subagent_sum("test", "success") == pytest.approx(before + 0.25)

    @pytest.mark.asyncio
    async def test_error_span_records_elapsed_seconds_not_the_summed_clock(self):
        async def _fake_astream(*args, **kwargs):
            raise RuntimeError("graph exploded")
            yield ("updates", {})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)
        before = _subagent_sum("test", "error")

        with (
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.time",
                new=_FakeClock(200.0, 200.5),
            ),
            pytest.raises(RuntimeError, match="graph exploded"),
        ):
            await execute_subagent_stream(
                ctx, stream_writer=MagicMock(), subagent_id="lat-clock-err"
            )

        assert _subagent_sum("test", "error") == pytest.approx(before + 0.5)


# ---------------------------------------------------------------------------
# reasoning sources: standard content blocks, and the provider fallback
# ---------------------------------------------------------------------------


async def _reasoning_frames(*chunks: AIMessageChunk) -> list[dict[str, Any]]:
    """Stream the chunks through a run and return the reasoning frames it wrote."""

    async def _fake_astream(*args, **kwargs):
        for chunk in chunks:
            yield ("messages", (chunk, {}))

    mock_graph = MagicMock()
    mock_graph.astream = _fake_astream
    writer = MagicMock()
    with patch("app.agents.core.subagents.subagent_runner.log"):
        await execute_subagent_stream(_make_ctx(subagent_graph=mock_graph), stream_writer=writer)
    return [c.args[0]["reasoning"] for c in writer.call_args_list if "reasoning" in c.args[0]]


class TestReasoningDeltaSources:
    async def test_a_standard_reasoning_block_streams_beside_the_answer_text(self):
        chunk = AIMessageChunk(
            content=[
                {"type": "text", "text": "Here is the plan."},
                {"type": "reasoning", "reasoning": "weighing two options"},
            ]
        )

        assert await _reasoning_frames(chunk) == [{"content": "weighing two options"}]

    async def test_several_reasoning_blocks_in_one_chunk_stream_as_one_delta(self):
        chunk = AIMessageChunk(
            content=[
                {"type": "reasoning", "reasoning": "first, "},
                {"type": "reasoning", "reasoning": "then second"},
            ]
        )

        assert await _reasoning_frames(chunk) == [{"content": "first, then second"}]

    async def test_a_v1_content_lists_bare_strings_are_not_reasoning(self):
        chunk = AIMessageChunk(
            content=["plain text", {"type": "reasoning", "reasoning": "checking the date"}],
            response_metadata={"output_version": "v1"},
        )

        assert await _reasoning_frames(chunk) == [{"content": "checking the date"}]

    async def test_a_non_string_provider_reasoning_field_is_streamed_as_text(self):
        # content_blocks only lifts a str reasoning_content; anything else takes the fallback.
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": {"step": 1}})

        assert await _reasoning_frames(chunk) == [{"content": "{'step': 1}"}]

    async def test_a_chunk_with_no_thinking_streams_no_reasoning(self):
        assert await _reasoning_frames(AIMessageChunk(content="just the answer")) == []


# ---------------------------------------------------------------------------
# the executor's targeted cancel, keyed by the subagent's own thread
# ---------------------------------------------------------------------------

SUBAGENT_THREAD = "spawn_c1_call-1"
_SUPERSTEP = ("updates", {"agent": {"messages": []}})


def _cancellable_run(*events: tuple[str, Any], stream_id: str | None = "s-1") -> Any:
    async def _fake_astream(*args, **kwargs):
        for event in events:
            yield event

    mock_graph = MagicMock()
    mock_graph.astream = _fake_astream
    return _make_ctx(
        subagent_graph=mock_graph,
        config={"configurable": {"thread_id": SUBAGENT_THREAD}},
        configurable={"thread_id": SUBAGENT_THREAD},
        stream_id=stream_id,
    )


async def _drive(ctx: SubagentExecutionContext) -> SubagentOutcome:
    with (
        patch("app.agents.core.subagents.subagent_runner.log"),
        patch(
            "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        return await execute_subagent_stream(ctx, stream_writer=MagicMock())


class TestTheExecutorsCancel:
    async def test_a_cancel_for_this_thread_stops_it_and_says_it_was_stopped(self, fake_redis):
        await SubagentCancel(SUBAGENT_THREAD).request()
        ctx = _cancellable_run(
            _SUPERSTEP, ("messages", (AIMessageChunk(content="should not reach"), {}))
        )

        outcome = await _drive(ctx)

        assert outcome.text == wrap_agent_payload(
            AgentTag.SUBAGENT_CANCELLED, "Stopped by the executor before finishing."
        )
        assert await SubagentCancel(SUBAGENT_THREAD).is_requested() is False

    async def test_what_it_said_before_the_cancel_is_what_the_executor_gets(self, fake_redis):
        await SubagentCancel(SUBAGENT_THREAD).request()
        ctx = _cancellable_run(
            ("messages", (AIMessageChunk(content="found 3 of 5 invoices"), {})), _SUPERSTEP
        )

        outcome = await _drive(ctx)

        assert outcome.text == wrap_agent_payload(
            AgentTag.SUBAGENT_CANCELLED, "found 3 of 5 invoices"
        )

    async def test_a_cancel_for_a_sibling_thread_does_not_stop_it(self, fake_redis):
        await SubagentCancel("spawn_c1_call-2").request()

        outcome = await _drive(_cancellable_run(_SUPERSTEP))

        assert outcome.text == "Task completed"
        assert await SubagentCancel("spawn_c1_call-2").is_requested() is True

    async def test_a_run_with_no_stream_is_not_cancellable(self, fake_redis):
        await SubagentCancel(SUBAGENT_THREAD).request()

        outcome = await _drive(_cancellable_run(_SUPERSTEP, stream_id=None))

        assert outcome.text == "Task completed"
        assert await SubagentCancel(SUBAGENT_THREAD).is_requested() is True

    async def test_the_stopped_segment_is_timed_as_cancelled_under_its_label(self, fake_redis):
        await SubagentCancel(SUBAGENT_THREAD).request()
        count_before = _subagent_count("test", "cancelled")
        sum_before = _subagent_sum("test", "cancelled")

        with patch("app.agents.core.subagents.subagent_runner.time", new=_FakeClock(10.0, 10.75)):
            await _drive(_cancellable_run(_SUPERSTEP))

        assert _subagent_count("test", "cancelled") == count_before + 1
        assert _subagent_sum("test", "cancelled") == pytest.approx(sum_before + 0.75)


# ---------------------------------------------------------------------------
# a decision resumes the interrupt it answers
# ---------------------------------------------------------------------------


class TestAResumeIsAddressedToItsInterrupt:
    async def test_with_several_pending_the_decision_goes_to_its_own_gate(self):
        captured: dict[str, Any] = {}

        async def _fake_astream(*args, **kwargs):
            captured["resume"] = args[0]
            yield ("updates", {"agent": {"messages": [AIMessage(content="sent")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_graph.aget_state = AsyncMock(
            return_value=MagicMock(
                next=("tools",),
                interrupts=(
                    Interrupt(value="not a gate payload", id="i-0"),
                    Interrupt(value={"approval_id": "a1"}, id="i-1"),
                    Interrupt(value={"approval_id": "a2"}, id="i-2"),
                ),
            )
        )
        decision = {"status": "approved", "approval_id": "a2"}

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(
                _make_ctx(subagent_graph=mock_graph), resume=Command(resume=decision)
            )

        assert captured["resume"].resume == {"i-2": decision}

    async def test_a_resume_keeps_its_update_and_is_re_clocked_in_the_users_zone(self):
        captured: dict[str, Any] = {}

        async def _fake_astream(*args, **kwargs):
            captured["resume"] = args[0]
            yield ("updates", {"agent": {"messages": [AIMessage(content="sent")]}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=("x",), next=None))
        ctx = _make_ctx(
            subagent_graph=mock_graph,
            configurable={"thread_id": "t1", "user_timezone": "Asia/Kolkata"},
        )
        note = HumanMessage(content="the user added a cc")

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await execute_subagent_stream(
                ctx, resume=Command(resume={"status": "approved"}, update={"messages": [note]})
            )

        carried, clock = captured["resume"].update["messages"]
        assert carried is note
        assert "User Local Time (Asia/Kolkata)" in clock.content
