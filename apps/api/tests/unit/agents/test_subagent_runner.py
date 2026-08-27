"""Unit tests for subagent_runner.py and subagent_helpers.py."""

from contextlib import contextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
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
    build_initial_messages,
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.llm.lane import AgentRole
from app.constants.llm import DEV_MODEL_OPTIONS, EXECUTOR_RECURSION_LIMIT
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
                tier=AgentTier.EXECUTOR,
                agent_name="test_agent",
                configurable={"user_timezone": "Asia/Kolkata"},
                task="Do the thing",
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
                tier=AgentTier.EXECUTOR,
                agent_name="agent",
                configurable={},
                task="task",
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
                tier=AgentTier.EXECUTOR,
                agent_name="agent",
                configurable={"user_timezone": "Asia/Kolkata"},
                task="task",
            )

        assert isinstance(result[-1], HumanMessage)
        assert result[-1].additional_kwargs.get("time_context") is True

    @pytest.mark.asyncio
    async def test_human_message_has_visible_to(self):
        with self._assembled():
            result = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.EXECUTOR,
                agent_name="my_agent",
                configurable={},
                task="task",
            )

        human_msg = next(m for m in result if m.type == "human" and m.content == "task")
        assert "my_agent" in human_msg.additional_kwargs["visible_to"]

    @pytest.mark.asyncio
    async def test_retrieval_query_defaults_to_task(self):
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.EXECUTOR,
                agent_name="agent",
                configurable={},
                task="my search query",
            )

        assert mock_assemble.call_args.args[0].query == "my search query"

    @pytest.mark.asyncio
    async def test_retrieval_query_overrides_an_enhanced_task(self):
        """The executor injects routing hints into the task text; retrieving
        against those would pollute the semantic search with our own words."""
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.EXECUTOR,
                agent_name="agent",
                configurable={},
                task="enhanced task with hints",
                retrieval_query="original query",
            )

        assert mock_assemble.call_args.args[0].query == "original query"

    @pytest.mark.asyncio
    async def test_tier_and_ids_reach_the_assembler(self):
        """The tier selects which sections apply, so passing the wrong one is
        how a subagent silently loses provider metadata."""
        with self._assembled() as mock_assemble:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                tier=AgentTier.PROVIDER_SUBAGENT,
                agent_name="agent",
                configurable={},
                task="task",
                user_id="uid-1",
                subagent_id="github_agent",
                integration_id="github",
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
        assert build_config.call_args.kwargs == {
            "conversation_id": "t1",
            "user": {"user_id": "u1", "email": "t@t.com", "name": "Test"},
            "thread_id": "executor_t1",
            "base_configurable": configurable,
            "agent_name": "executor_agent",
            "role": AgentRole.EXECUTOR,
            "dev_option": None,
            "subagent_id": "executor_agent",
            "vfs_session_id": "t1",
            "recursion_limit": EXECUTOR_RECURSION_LIMIT,
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

        assert build_config.call_args.kwargs["dev_option"] == DEV_MODEL_OPTIONS["minimax-m3"]

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

        assert build_config.call_args.kwargs["dev_option"] is None

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
        assert call_kwargs["vfs_session_id"] == "t1"


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
