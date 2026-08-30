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
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import PromptSlot
from app.agents.context.tiers import AgentTier
from app.agents.core.background import redis_writer as rw, session as sess
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import RunKind, StreamSession, create_session
from app.agents.core.graph_manager import GraphUnavailableError
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
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
from app.constants.hil import LANGGRAPH_INTERRUPT_KEY
from app.constants.llm import DEV_MODEL_OPTIONS, EXECUTOR_RECURSION_LIMIT
from app.helpers.agent_helpers import AgentIdentity, AgentLane, AgentThread
from app.models.mcp_config import SubAgentConfig
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
        handoff_tool_name="call_github",
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
    """One in-flight ``execute_subagent_stream`` drive, without the stream.

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
    """Subagent-shaped fixture for `get_subagent_by_id` (used by
    `build_subagent_system_prompt`).

    Mirrors the `Subagent` dataclass surface: `.id`, `.name`, `.short_name`,
    `.provider`, and `.config` with `.agent_name`, `.system_prompt`, and
    `.has_subagent`.
    """
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
    """Shape is ``[static, dynamic_stable, memory_recall?, human_task, time]`` —
    canonical slot order, so the pre-model hooks normalise correct input rather
    than correcting this tier's output."""

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
        """It has to stay inside the leading system block — Gemini drops any
        system message that follows a non-system one."""
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
        """The executor injects routing hints into the task text; retrieving
        against those would pollute the semantic search with our own words."""
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
    async def test_tier_and_ids_reach_the_assembler(self):
        """The tier selects which sections apply, so passing the wrong one is
        how a subagent silently loses provider metadata."""
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
        """The outcome carries this run's tool-bearing messages — the agent
        node's complete AIMessages plus the ToolMessages answering them — which
        is what the workflow call record is built from."""
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
        """Pre-model hooks replay historical AIMessages in their updates; those
        must not leak stale tool calls into the record."""
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
        """Updates from non-agent nodes (pre-model hooks) must not emit tool_data.

        When a subagent runs a second time with the same checkpoint, LangGraph
        replays historical AIMessages via filter_messages_node / manage_system_prompts_node
        "updates" events. Without the guard these stale tool_calls get re-emitted,
        causing cumulative duplication in the UI (e.g. "13 tools" instead of 3).
        """
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
        """The id the caller passes is what nests every event in the subagent's
        row; dropped, the client renders the result outside the row it belongs to.
        """
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
    """The "updates" branch, called directly: what it records, what it forwards
    to the tool-entry extractor, and the exact chunk it writes."""

    @staticmethod
    def _entries(entries: list[tuple[str, dict[str, Any]]]) -> Any:
        return patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=entries,
        )

    @pytest.mark.asyncio
    async def test_an_interrupt_event_records_its_payloads_and_stops_there(self):
        """The approval values come out of the event's own ``__interrupt__``
        entry — accumulated, because one event arrives per paused task."""
        run = _make_run()
        payload = {LANGGRAPH_INTERRUPT_KEY: ({"approval_id": "a1"}, {"approval_id": "a2"})}

        with patch("app.agents.core.subagents.subagent_runner.log"):
            await _process_updates_payload(run, payload)

        assert run.pending_approvals == [{"approval_id": "a1"}, {"approval_id": "a2"}]
        assert run.run_messages == []

    @pytest.mark.asyncio
    async def test_a_non_agent_node_is_skipped_without_abandoning_the_rest(self):
        """Skipping the pre-model hook must ``continue``, not ``break`` — the
        agent node's update arrives in the SAME payload behind it."""
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
        """The default is an empty list, not ``None`` — a node update that
        carries no messages at all is ordinary, not a crash."""
        run = _make_run()

        with patch("app.agents.core.subagents.subagent_runner.log"), self._entries([]):
            await _process_updates_payload(run, {"agent": {"todos": []}})

        assert run.run_messages == []

    @pytest.mark.asyncio
    async def test_only_tool_bearing_messages_are_captured(self):
        """The filter reads ``tool_calls`` defensively: the agent node's update
        also carries messages that have no such attribute at all."""
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
        """``note_tool_output_owner`` is what stops "messages" mode re-emitting
        the same ToolMessage untagged — all three arguments decide the claim."""
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
    """The "messages" branch hands five positional arguments down, and every one
    of them decides where the chunk's output is routed."""

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
    """What a drained (or paused) run turns into, and the wide-event fields the
    outcome is stamped with."""

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

    def test_an_announced_tool_call_makes_the_same_text_an_ordinary_result(self):
        """The second half of the narration guard: a run that announced a call
        did the work, even if no ToolMessage came back before the stream ended.
        """
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
        """The executor gets its OWN config, derived from comms's. Every argument
        here is load-bearing: the thread it resumes on, the bag it inherits (which
        carries comms's resolved lane), its memory namespace, its VFS session and
        its deeper recursion budget.
        """
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
    async def test_the_dev_executor_model_comms_stashed_becomes_this_runs_dev_option(self):
        """DEV-ONLY: without this the executor silently inherits comms's lane and
        the header's executor picker does nothing."""
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
        """Every ThreadSeed field is load-bearing: the tier decides which context
        sections apply, the user id scopes what they retrieve, and the query has
        to stay the ORIGINAL task — the workflow section injected into
        ``enhanced_task`` would otherwise pollute the semantic search."""
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
        """The static subagent prompt must be byte-identical across users.

        Provider metadata (usernames, emails) is assembled separately by
        ``app.agents.context`` and delivered in its own message, so the static
        prefix the LLM receives stays cacheable.
        """
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.context.sections.get_provider_metadata",
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
    sess._sessions.clear()
    session = create_session(stream_id, RunKind.QUEUED)
    with patch.object(rw, "stream_manager") as stream_manager:
        stream_manager.publish_chunk = AsyncMock()
        yield make_redis_stream_writer(stream_id), stream_manager, session
    sess._sessions.clear()


def _published_reasoning(stream_manager: MagicMock) -> list[str]:
    frames = [
        json.loads(call[0][1].removeprefix("data: "))
        for call in stream_manager.publish_chunk.call_args_list
    ]
    return [frame["reasoning"]["content"] for frame in frames if "reasoning" in frame]


def _collected_reasoning(session: StreamSession) -> list[str]:
    return [evt["reasoning"]["content"] for evt in session.tool_events if "reasoning" in evt]


class TestReasoningStreamsPerDeltaButPersistsPerBlock:
    """The live stream must stay token by token — that is what makes thinking
    visible as it happens. What must not stay per token is the SAVE: every
    published event is also appended to the stream session, which is persisted
    verbatim, and one prod conversation ended up carrying ~22k reasoning entries.
    So the publish is untouched and the collector coalesces each contiguous run
    of thinking into one entry."""

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
        """What is persisted is the DRAINED shape, not the raw collector — the
        entry count has to survive absorb_collector_event too."""
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
        """Merging on adjacency alone would splice one subagent's thinking into
        another's block, and the block carries the subagent_id that nests it."""
        with _real_stream_writer() as (writer, _stream_manager, session):
            writer({"reasoning": {"content": "alpha ", "subagent_id": "sub-1"}})
            writer({"reasoning": {"content": "beta", "subagent_id": "sub-2"}})
            writer({"reasoning": {"content": " more", "subagent_id": "sub-2"}})

            assert _collected_reasoning(session) == ["alpha ", "beta more"]
