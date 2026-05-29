"""Unit tests for subagent_runner.py (and subagent_helpers.py support).

================================================================================
BEHAVIOR SPEC — app/agents/core/subagents/subagent_runner.py
================================================================================

UNIT: _capture_finish_task_content(chunk, current_message)
EXPECTED: Return the chunk's textual content ONLY when it is a finish_task
          ToolMessage with str content; otherwise return current_message unchanged.
MECHANISM: `if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
            return chunk.content; return current_message`.
MUST-CATCH:
  - finish_task + str content -> returns the chunk content (not the prior message)
  - non-finish_task name -> returns prior message unchanged (name gate)
  - finish_task with non-str content -> returns prior message (isinstance gate)

UNIT: build_initial_messages(...)
EXPECTED: Return [static_system, dynamic_context, time_HumanMessage, task_HumanMessage].
MECHANISM: builds context via create_agent_context_message, time via
           build_current_time_message; task HumanMessage carries visible_to={agent}.
MUST-CATCH:
  - exactly 4 messages, in that order, with the real objects
  - task content is the given task; visible_to contains the given agent_name
  - retrieval_query defaults to task, but the explicit override wins (None vs value)
  - user_id / subagent_id / integration_id / memories_text / skills_text forwarded

UNIT: prepare_subagent_execution(...)
EXPECTED: (ctx, None) on success; (None, error) when the id is unknown or graph absent.
MECHANISM: strips "subagent:" prefix, resolves subagent, loads graph via providers.aget,
           builds config (thread_id = f"{id}_{conversation_id}"), builds messages.
MUST-CATCH:
  - unknown id -> (None, "Subagent '<raw>' not found. ...") and the raw id is echoed
  - graph missing -> (None, "Subagent <agent_name> not available")
  - "subagent:" prefix stripped before lookup
  - thread_id passed to build_agent_config is exactly "{subagent.id}_{conversation_id}"
  - subagent.id (not agent_name) becomes ctx.integration_id; agent_name -> ctx.agent_name
  - pinned memories/skills from base_configurable forwarded into build_initial_messages

UNIT: execute_subagent_stream(ctx, stream_writer, integration_metadata, subagent_id)
EXPECTED: Accumulate AIMessageChunk text -> return it; emit tool_data/tool_output/custom
          frames to stream_writer; honour cancellation; default "Task completed".
MECHANISM: astream over ["messages","custom","updates"]; only "agent"-node updates emit
           tool_data; ToolMessage emits tool_output (truncated 3000) + captures finish_task.
MUST-CATCH:
  - AI text accumulated and returned verbatim
  - empty/silent -> "Task completed" fallback
  - tool_output frame: key "tool_output", tool_call_id, output truncated to 3000
  - tool_data frame from "agent" node; non-agent nodes never emit (stale-replay guard)
  - subagent_id injection: tool_data and tool_output carry the subagent_id
  - custom events forwarded via normalize_custom_event payload
  - cancellation after first chunk stops accumulation
  - non-2-tuple events skipped
  - finish_task ToolMessage content becomes the returned message

UNIT: prepare_executor_execution(...)
EXPECTED: (ctx, None) with executor graph + thread_id "executor_{thread}_{scope}";
          inject DIRECT EXECUTION HINT only when tool_category resolves to a subagent.
MECHANISM: GraphManager.get_graph("executor_agent"); vfs_session_id falls back to thread_id;
           hint text embeds tool_category + selected_tool.
MUST-CATCH:
  - graph missing -> (None, "Executor agent not available")
  - executor_thread_id passed to build_agent_config starts "executor_{thread_id}_"
  - vfs_session_id passed = configurable["vfs_session_id"] when present, else thread_id
  - agent_name="executor_agent" passed to build_agent_config
  - hint injected (with tool_category + selected_tool text) only when subagent resolves
  - no hint when tool_category absent OR resolves to no subagent
  - retrieval_query is the ORIGINAL task (not the hinted one)
  - stream_id propagated onto ctx

UNIT: check_subagent_integration(integration_id, user_id)
EXPECTED: None when connected; "Integration {id} is not connected..." when not;
          None (swallowed) on exception.
MUST-CATCH: connected->None; disconnected->message echoing the integration_id; raise->None.

UNIT: call_subagent(...)
EXPECTED: Async SSE generator. On prepare failure or integration failure yields an
          error frame + [DONE]. On success streams response/tool_data/tool_output/custom
          then a final nostream complete_message + [DONE].
MECHANISM: optional integration check (skip_integration_check False), prepare, astream.
MUST-CATCH:
  - prepare failure -> data:{"error":...} then data:[DONE], exactly 2 frames
  - integration not connected (check enabled) -> error frame echoes message + [DONE]
  - default skip_integration_check=True -> check_subagent_integration NOT awaited
  - AI chunk -> data:{"response": content}
  - tool_data frame on "agent" updates; non-agent updates suppressed
  - ToolMessage -> data:{"tool_output":{tool_call_id, output[:3000]}}
  - finish_task ToolMessage ALSO emits data:{"response": content}
  - custom event -> forwarded normalized
  - cancellation stops after first chunk
  - always terminates with nostream complete_message + [DONE]

EQUIVALENT MUTANTS (allowed survivors, justified):
  - String fragments that flow EXCLUSIVELY into log.set/log.info payloads are
    observability-only and cannot change the returned/streamed values; the harness
    skips most, and any nested f-string fragments that remain do not alter behaviour.
  - The executor thread "scope" suffix length (uuid hex[:12], 12->13): the suffix is
    a random opaque token; only the "executor_{thread}_" PREFIX is behaviourally
    load-bearing, so the slice length is behaviour-preserving for any consumer.
"""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
import pytest

from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    _capture_finish_task_content,
    build_initial_messages,
    call_subagent,
    check_subagent_integration,
    execute_subagent_stream,
    prepare_executor_execution,
    prepare_subagent_execution,
)
from app.constants.general import FINISH_TASK_NAME
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent

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
        managed_by=managed_by,  # type: ignore[arg-type]
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
    return SubagentExecutionContext(**defaults)  # type: ignore[arg-type]


def _astream_of(*events):
    """Build an async-generator astream that yields the given events."""

    async def _gen(*args, **kwargs):
        for ev in events:
            yield ev

    return _gen


def _empty_astream():
    async def _gen(*args, **kwargs):
        return
        yield  # NOSONAR — unreachable: makes this an async generator

    return _gen


def _capturing_astream(captured: dict, *events):
    """astream that records the call kwargs (config, stream_mode) into ``captured``."""

    async def _gen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        for ev in events:
            yield ev

    return _gen


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
# _capture_finish_task_content
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaptureFinishTaskContent:
    def test_finish_task_str_content_replaces_message(self):
        """A finish_task ToolMessage with str content becomes the captured message."""
        chunk = ToolMessage(content="The final answer", tool_call_id="tc-1", name=FINISH_TASK_NAME)
        assert _capture_finish_task_content(chunk, "prior") == "The final answer"

    def test_non_finish_task_keeps_prior_message(self):
        """Any other tool name leaves the running message untouched (name gate)."""
        chunk = ToolMessage(content="search hits", tool_call_id="tc-1", name="web_search")
        assert _capture_finish_task_content(chunk, "prior") == "prior"

    def test_finish_task_non_str_content_keeps_prior_message(self):
        """finish_task with structured (non-str) content does not capture (isinstance gate)."""
        chunk = ToolMessage(content=[{"k": "v"}], tool_call_id="tc-1", name=FINISH_TASK_NAME)
        assert _capture_finish_task_content(chunk, "prior") == "prior"


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildInitialMessages:
    @pytest.mark.asyncio
    async def test_message_order_and_objects(self):
        """Shape is [static, dynamic_context, time_msg, human_task] with the real objects.

        The time HumanMessage is separated from the user task so minute ticks
        don't reset the ``system_instruction`` cache boundary.
        """
        sys_msg = SystemMessage(content="System prompt")
        ctx_msg = SystemMessage(content="Context")

        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new_callable=AsyncMock,
            return_value=ctx_msg,
        ):
            result = await build_initial_messages(
                system_message=sys_msg,
                agent_name="test_agent",
                configurable={"user_timezone": "UTC"},
                task="Do the thing",
            )

        assert len(result) == 4
        assert result[0] is sys_msg
        assert result[1] is ctx_msg
        # result[2] is the build_current_time_message HumanMessage
        assert isinstance(result[2], HumanMessage)
        assert result[2].additional_kwargs.get("time_context") is True
        # result[3] is the task
        assert isinstance(result[3], HumanMessage)
        assert result[3].content == "Do the thing"

    @pytest.mark.asyncio
    async def test_time_message_built_from_configurable_timezone(self):
        """build_current_time_message receives configurable['user_timezone']."""
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_current_time_message",
                return_value=HumanMessage(content="time"),
            ) as mock_time,
        ):
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                configurable={"user_timezone": "America/New_York"},
                task="task",
            )

        assert mock_time.call_args.kwargs["user_timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_task_human_message_visible_to_agent(self):
        """The task message is addressed to exactly the given agent_name."""
        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new_callable=AsyncMock,
            return_value=SystemMessage(content="ctx"),
        ):
            result = await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="my_agent",
                configurable={},
                task="task",
            )

        human_msg = result[3]
        assert human_msg.additional_kwargs["visible_to"] == {"my_agent"}

    @pytest.mark.asyncio
    async def test_retrieval_query_defaults_to_task(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new_callable=AsyncMock,
            return_value=SystemMessage(content="ctx"),
        ) as mock_ctx:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                configurable={},
                task="my search query",
            )

        assert mock_ctx.call_args.kwargs["query"] == "my search query"

    @pytest.mark.asyncio
    async def test_retrieval_query_override_wins(self):
        """An explicit retrieval_query overrides task; the None-default branch must flip."""
        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new_callable=AsyncMock,
            return_value=SystemMessage(content="ctx"),
        ) as mock_ctx:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                configurable={},
                task="enhanced task with hints",
                retrieval_query="original query",
            )

        assert mock_ctx.call_args.kwargs["query"] == "original query"

    @pytest.mark.asyncio
    async def test_context_args_forwarded(self):
        """user_id / subagent_id / integration_id / memories / skills flow through verbatim."""
        with patch(
            "app.agents.core.subagents.subagent_runner.create_agent_context_message",
            new_callable=AsyncMock,
            return_value=SystemMessage(content="ctx"),
        ) as mock_ctx:
            await build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="agent",
                configurable={},
                task="task",
                user_id="uid-1",
                subagent_id="github_agent",
                integration_id="github",
                memories_text="pinned mem",
                skills_text="pinned skills",
            )

        kwargs = mock_ctx.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["subagent_id"] == "github_agent"
        assert kwargs["integration_id"] == "github"
        assert kwargs["memories_text"] == "pinned mem"
        assert kwargs["skills_text"] == "pinned skills"


# ---------------------------------------------------------------------------
# prepare_subagent_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareSubagentExecution:
    @pytest.mark.asyncio
    async def test_happy_path_returns_ctx_with_ids_and_graph(self):
        mock_graph = MagicMock(name="subagent_graph")
        github = _make_subagent("github", "gh", "github_agent", "github")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "github_conv-1", "marker": "X"}},
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="GitHub system"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="github",
                task="List my repos",
                user={"user_id": "u1", "email": "t@t.com", "name": "T"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert error is None
        assert ctx is not None
        assert ctx.agent_name == "github_agent"
        # integration_id is the subagent.id, NOT the agent_name
        assert ctx.integration_id == "github"
        assert ctx.subagent_graph is mock_graph
        # user_id pulled from the user dict; configurable lifted from build_agent_config
        assert ctx.user_id == "u1"
        assert ctx.configurable == {"thread_id": "github_conv-1", "marker": "X"}
        # initial_state carries the built messages + empty todos
        assert ctx.initial_state["todos"] == []
        assert len(ctx.initial_state["messages"]) == 4

    @pytest.mark.asyncio
    async def test_thread_id_is_subagent_id_underscore_conversation(self):
        """build_agent_config receives thread_id == f"{subagent.id}_{conversation_id}"."""
        mock_graph = MagicMock(name="subagent_graph")
        github = _make_subagent("github", "gh", "github_agent", "github")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ) as mock_build,
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            await prepare_subagent_execution(
                subagent_id="github",
                task="t",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-XYZ",
            )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["thread_id"] == "github_conv-XYZ"
        # agent_name (not raw id) is used as the agent for the subagent run
        assert kwargs["agent_name"] == "github_agent"
        assert kwargs["subagent_id"] == "github_agent"

    @pytest.mark.asyncio
    async def test_pinned_memories_and_skills_forwarded(self):
        """base_configurable __pinned_* values reach build_initial_messages -> context."""
        mock_graph = MagicMock(name="subagent_graph")
        github = _make_subagent("github", "gh", "github_agent", "github")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ) as mock_ctx,
        ):
            await prepare_subagent_execution(
                subagent_id="github",
                task="t",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
                base_configurable={
                    "__pinned_memories__": "MEM-BLOCK",
                    "__pinned_skills__": "SKILL-BLOCK",
                },
            )

        kwargs = mock_ctx.call_args.kwargs
        assert kwargs["memories_text"] == "MEM-BLOCK"
        assert kwargs["skills_text"] == "SKILL-BLOCK"

    @pytest.mark.asyncio
    async def test_subagent_not_found_error_echoes_raw_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.all_subagents",
                return_value=FAKE_SUBAGENTS,
            ),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="nonexistent",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert ctx is None
        assert error == "Subagent 'nonexistent' not found. Available: github, gmail"

    @pytest.mark.asyncio
    async def test_not_found_lists_first_five_with_ellipsis(self):
        """With >=5 available subagents, the message lists exactly 5 and ends with '...'."""
        many = tuple(_make_subagent(f"agent{i}") for i in range(7))
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.all_subagents",
                return_value=many,
            ),
        ):
            _, error = await prepare_subagent_execution(
                subagent_id="missing",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert error == (
            "Subagent 'missing' not found. Available: agent0, agent1, agent2, agent3, agent4..."
        )

    @pytest.mark.asyncio
    async def test_not_found_under_five_has_no_ellipsis(self):
        """Fewer than 5 available -> no trailing '...' (the len==5 branch must matter)."""
        few = (_make_subagent("only_one"),)
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.all_subagents",
                return_value=few,
            ),
        ):
            _, error = await prepare_subagent_execution(
                subagent_id="missing",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert error == "Subagent 'missing' not found. Available: only_one"
        assert "..." not in error

    @pytest.mark.asyncio
    async def test_graph_not_available_error(self):
        github = _make_subagent("github", "gh", "github_agent", "github")
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="github",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert ctx is None
        assert error == "Subagent github_agent not available"

    @pytest.mark.asyncio
    async def test_strips_subagent_prefix_before_lookup_and_graph(self):
        """'subagent:github' resolves via the stripped 'github' and loads its agent graph."""
        mock_graph = MagicMock(name="subagent_graph")
        github = _make_subagent("github", "gh", "github_agent", "github")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ) as mock_lookup,
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_aget,
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="subagent:github",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(UTC),
                conversation_id="conv-1",
            )

        assert error is None
        assert ctx is not None
        mock_lookup.assert_called_once_with("github")
        # graph loaded by agent_name, not the raw/stripped id
        mock_aget.assert_awaited_once_with("github_agent")


# ---------------------------------------------------------------------------
# execute_subagent_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteSubagentStream:
    @pytest.mark.asyncio
    async def test_accumulates_ai_content(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="Hello "), {})),
            ("messages", (AIMessageChunk(content="world"), {})),
        )
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx)
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_silent_messages_skipped_default_returned(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="should skip"), {"silent": True}))
        )
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx)
        assert result == "Task completed"  # default when no content accumulated

    @pytest.mark.asyncio
    async def test_empty_stream_returns_default(self):
        mock_graph = MagicMock()
        mock_graph.astream = _empty_astream()
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx)
        assert result == "Task completed"

    @pytest.mark.asyncio
    async def test_tool_message_emits_tool_output_frame(self):
        tool_msg = ToolMessage(content="tool result data", tool_call_id="tc-1")
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        await execute_subagent_stream(ctx, stream_writer=stream_writer)

        call_data = stream_writer.call_args[0][0]
        assert set(call_data.keys()) == {"tool_output"}
        assert call_data["tool_output"]["tool_call_id"] == "tc-1"
        assert call_data["tool_output"]["output"] == "tool result data"

    @pytest.mark.asyncio
    async def test_tool_output_truncated_to_3000(self):
        tool_msg = ToolMessage(content="x" * 5000, tool_call_id="tc-2")
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        await execute_subagent_stream(ctx, stream_writer=stream_writer)

        output = stream_writer.call_args[0][0]["tool_output"]["output"]
        assert len(output) == 3000
        assert output == "x" * 3000

    @pytest.mark.asyncio
    async def test_finish_task_tool_message_becomes_return(self):
        """A finish_task ToolMessage's content becomes the returned message."""
        finish = ToolMessage(content="THE FINAL ANSWER", tool_call_id="tc-9", name=FINISH_TASK_NAME)
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (finish, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx)
        assert result == "THE FINAL ANSWER"

    @pytest.mark.asyncio
    async def test_tool_output_carries_subagent_id_when_provided(self):
        tool_msg = ToolMessage(content="r", tool_call_id="tc-1")
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        await execute_subagent_stream(ctx, stream_writer=stream_writer, subagent_id="uuid-123")

        assert stream_writer.call_args[0][0]["tool_output"]["subagent_id"] == "uuid-123"

    @pytest.mark.asyncio
    async def test_tool_output_omits_subagent_id_when_absent(self):
        """Without subagent_id, the tool_output frame has no subagent_id key."""
        tool_msg = ToolMessage(content="r", tool_call_id="tc-1")
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        await execute_subagent_stream(ctx, stream_writer=stream_writer)

        assert "subagent_id" not in stream_writer.call_args[0][0]["tool_output"]

    @pytest.mark.asyncio
    async def test_updates_emit_tool_data_from_agent_node(self):
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("updates", {"agent": {"messages": []}}))
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[("tc-1", tool_entry)],
        ):
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        call_data = stream_writer.call_args[0][0]
        assert call_data == {"tool_data": tool_entry}

    @pytest.mark.asyncio
    async def test_tool_data_carries_subagent_id_when_provided(self):
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("updates", {"agent": {"messages": []}}))
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[("tc-1", tool_entry)],
        ):
            await execute_subagent_stream(ctx, stream_writer=stream_writer, subagent_id="uuid-9")

        emitted = stream_writer.call_args[0][0]["tool_data"]
        assert emitted["subagent_id"] == "uuid-9"
        assert emitted["name"] == "web_search"

    @pytest.mark.asyncio
    async def test_non_agent_node_updates_skipped(self):
        """Updates from non-agent nodes (pre-model hooks) must not emit tool_data.

        When a subagent runs again with the same checkpoint, LangGraph replays
        historical AIMessages via filter_messages_node / manage_system_prompts_node
        "updates" events. Without the guard these stale tool_calls re-emit, causing
        cumulative duplication in the UI.
        """
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("updates", {"filter_messages_node": {"messages": []}}),
            ("updates", {"manage_system_prompts_node": {"messages": []}}),
            ("updates", {"agent": {"messages": []}}),
        )
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[("tc-1", tool_entry)],
        ) as mock_extract:
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        # Only the "agent" node is extracted from; the two hook nodes are skipped.
        assert mock_extract.await_count == 1
        stream_writer.assert_called_once_with({"tool_data": tool_entry})

    @pytest.mark.asyncio
    async def test_custom_events_forwarded_normalized(self):
        custom_payload = {"progress": "50%"}
        normalized = {"progress": "50%", "normalized": True}
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("custom", custom_payload))
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch(
            "app.agents.core.subagents.subagent_runner.normalize_custom_event",
            return_value=normalized,
        ) as mock_norm:
            await execute_subagent_stream(ctx, stream_writer=stream_writer)

        mock_norm.assert_called_once_with(custom_payload)
        stream_writer.assert_called_once_with(normalized)

    @pytest.mark.asyncio
    async def test_no_stream_writer_no_errors(self):
        """When stream_writer is None, tool/custom frames are silently skipped."""
        tool_msg = ToolMessage(content="result", tool_call_id="tc-1")
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (tool_msg, {})),
            ("custom", {"progress": "done"}),
            ("messages", (AIMessageChunk(content="hi"), {})),
        )
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx, stream_writer=None)
        assert result == "hi"

    @pytest.mark.asyncio
    async def test_cancellation_breaks_stream(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="First "), {})),
            ("messages", (AIMessageChunk(content="Second"), {})),
        )
        ctx = _make_ctx(subagent_graph=mock_graph, stream_id="s-1")

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
            new_callable=AsyncMock,
            side_effect=[False, True],
        ):
            result = await execute_subagent_stream(ctx)

        # Only the first chunk processed before cancellation fires on the second.
        assert result == "First "

    @pytest.mark.asyncio
    async def test_no_cancellation_check_without_stream_id(self):
        """When ctx.stream_id is falsy, is_cancelled is never consulted."""
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="A"), {})),
            ("messages", (AIMessageChunk(content="B"), {})),
        )
        ctx = _make_ctx(subagent_graph=mock_graph, stream_id=None)

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_cancel:
            result = await execute_subagent_stream(ctx)

        mock_cancel.assert_not_awaited()
        assert result == "AB"

    @pytest.mark.asyncio
    async def test_non_tuple_events_skipped(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("a", "b", "c"),  # 3-tuple -> skipped
            ("messages", (AIMessageChunk(content="ok"), {})),
        )
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_integration_metadata_passed_to_extract(self):
        metadata = {"icon_url": "https://icon.png", "name": "Custom MCP"}
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("updates", {"agent": {"messages": []}}))
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch(
            "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_extract:
            await execute_subagent_stream(ctx, integration_metadata=metadata)

        assert mock_extract.call_args.kwargs["integration_metadata"] is metadata

    @pytest.mark.asyncio
    async def test_subagent_id_injected_into_run_config(self):
        """When subagent_id is given, astream config.configurable carries it so nested
        spawn_subagent calls read the correct parent id."""
        captured: dict = {}
        mock_graph = MagicMock()
        mock_graph.astream = _capturing_astream(captured)
        ctx = _make_ctx(
            subagent_graph=mock_graph,
            config={"configurable": {"thread_id": "t1", "existing": "kept"}},
        )

        await execute_subagent_stream(ctx, subagent_id="parent-uuid")

        run_config = captured["kwargs"]["config"]
        assert run_config["configurable"]["subagent_id"] == "parent-uuid"
        # existing configurable entries are preserved
        assert run_config["configurable"]["existing"] == "kept"

    @pytest.mark.asyncio
    async def test_run_config_unchanged_without_subagent_id(self):
        """No subagent_id -> the original ctx.config is used verbatim."""
        captured: dict = {}
        original_config = {"configurable": {"thread_id": "t1"}}
        mock_graph = MagicMock()
        mock_graph.astream = _capturing_astream(captured)
        ctx = _make_ctx(subagent_graph=mock_graph, config=original_config)

        await execute_subagent_stream(ctx)

        assert captured["kwargs"]["config"] is original_config
        assert "subagent_id" not in captured["kwargs"]["config"]["configurable"]

    @pytest.mark.asyncio
    async def test_stream_mode_requests_all_three_channels(self):
        """astream is invoked over messages + custom + updates, in that order."""
        captured: dict = {}
        mock_graph = MagicMock()
        mock_graph.astream = _capturing_astream(captured)
        ctx = _make_ctx(subagent_graph=mock_graph)

        await execute_subagent_stream(ctx)

        assert captured["kwargs"]["stream_mode"] == ["messages", "custom", "updates"]

    @pytest.mark.asyncio
    async def test_non_ai_non_tool_chunk_ignored(self):
        """A truthy chunk that is neither AIMessageChunk nor ToolMessage produces no
        tool_output and does not crash (the `isinstance(chunk, ToolMessage)` guard)."""
        stray = HumanMessage(content="stray")
        stream_writer = MagicMock()
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (stray, {})))
        ctx = _make_ctx(subagent_graph=mock_graph)

        result = await execute_subagent_stream(ctx, stream_writer=stream_writer)

        stream_writer.assert_not_called()
        assert result == "Task completed"


# ---------------------------------------------------------------------------
# check_subagent_integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckSubagentIntegration:
    @pytest.mark.asyncio
    async def test_connected_returns_none(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.check_integration_status",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await check_subagent_integration("github", "u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_connected_returns_message_with_id(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.check_integration_status",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await check_subagent_integration("slack", "u1")
        assert result == "Integration slack is not connected. Please connect it first."

    @pytest.mark.asyncio
    async def test_exception_swallowed_returns_none(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.check_integration_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await check_subagent_integration("github", "u1")
        assert result is None


# ---------------------------------------------------------------------------
# prepare_executor_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareExecutorExecution:
    @pytest.mark.asyncio
    async def test_happy_path_returns_executor_ctx(self):
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_get_graph,
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "executor_t1"}},
            ) as mock_build,
            patch(
                "app.agents.core.subagents.subagent_runner.create_system_message",
                return_value=SystemMessage(content="executor sys"),
            ) as mock_sysmsg,
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
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
                user_time=datetime.now(UTC),
            )

        assert error is None
        assert ctx is not None
        assert ctx.agent_name == "executor_agent"
        assert ctx.integration_id == "executor"
        assert ctx.subagent_graph is mock_graph
        assert ctx.user_id == "u1"
        assert ctx.initial_state["todos"] == []
        # Executor graph resolved by its registered name.
        mock_get_graph.assert_awaited_once_with("executor_agent")
        # The user dict forwarded to build_agent_config carries id/email/name
        # pulled from the right configurable keys.
        assert mock_build.call_args.kwargs["user"] == {
            "user_id": "u1",
            "email": "t@t.com",
            "name": "Test",
        }
        # Executor-specific system prompt requested with the right agent_type + name.
        sys_kwargs = mock_sysmsg.call_args.kwargs
        assert sys_kwargs["agent_type"] == "executor"
        assert sys_kwargs["user_name"] == "Test"
        assert sys_kwargs["user_id"] == "u1"
        # The executor task message is addressed to the executor agent.
        assert ctx.initial_state["messages"][-1].additional_kwargs["visible_to"] == {
            "executor_agent"
        }

    @pytest.mark.asyncio
    async def test_executor_thread_id_and_agent_name(self):
        """executor_thread_id passed to build_agent_config is 'executor_{thread}_<scope>'
        and the run is configured for the 'executor_agent'."""
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ) as mock_build,
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "thrd-1"},
                user_time=datetime.now(UTC),
            )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["thread_id"].startswith("executor_thrd-1_")
        # the random scope suffix is appended after the prefix
        assert kwargs["thread_id"] != "executor_thrd-1_"
        assert kwargs["agent_name"] == "executor_agent"
        assert kwargs["subagent_id"] == "executor_agent"
        # conversation_id is the parent thread, not the ephemeral executor thread
        assert kwargs["conversation_id"] == "thrd-1"

    @pytest.mark.asyncio
    async def test_executor_graph_unavailable(self):
        with patch(
            "app.agents.core.graph_manager.GraphManager.get_graph",
            new_callable=AsyncMock,
            return_value=None,
        ):
            ctx, error = await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                user_time=datetime.now(UTC),
            )

        assert ctx is None
        assert error == "Executor agent not available"

    @pytest.mark.asyncio
    async def test_direct_handoff_hint_injected_with_tool_names(self):
        """tool_category resolving to a subagent injects a hint naming category+tool."""
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
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
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
                user_time=datetime.now(UTC),
            )

        assert error is None
        content = ctx.initial_state["messages"][-1].content
        assert content.startswith("search repos")
        assert "DIRECT EXECUTION HINT" in content
        assert 'handoff(subagent_id="github"' in content
        # selected_tool flows into the hint wording
        assert "the 'github_search_repos' tool" in content

    @pytest.mark.asyncio
    async def test_hint_without_selected_tool_uses_generic_phrase(self):
        """No selected_tool -> hint routes 'the user's request' instead of a tool name."""
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
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
        ):
            ctx, _ = await prepare_executor_execution(
                task="do it",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "tool_category": "github",
                },
                user_time=datetime.now(UTC),
            )

        content = ctx.initial_state["messages"][-1].content
        # Generic routing phrase, not the "the '<tool>' tool" wording.
        assert "route the user's request." in content
        assert "' tool." not in content

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
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            ctx, _ = await prepare_executor_execution(
                task="plain task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                user_time=datetime.now(UTC),
            )

        content = ctx.initial_state["messages"][-1].content
        assert "DIRECT EXECUTION HINT" not in content
        assert content == "plain task"

    @pytest.mark.asyncio
    async def test_no_hint_when_tool_category_not_a_subagent(self):
        """tool_category present but unknown to the registry -> no hint."""
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=None,
            ),
        ):
            ctx, _ = await prepare_executor_execution(
                task="plain task",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "tool_category": "unknown_cat",
                },
                user_time=datetime.now(UTC),
            )

        assert "DIRECT EXECUTION HINT" not in ctx.initial_state["messages"][-1].content

    @pytest.mark.asyncio
    async def test_retrieval_query_is_original_task_not_hint(self):
        """Memory/context retrieval uses the un-hinted task, even when a hint is added."""
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
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ) as mock_ctx,
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
        ):
            await prepare_executor_execution(
                task="clean query",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "tool_category": "github",
                    "selected_tool": "x",
                },
                user_time=datetime.now(UTC),
            )

        assert mock_ctx.call_args.kwargs["query"] == "clean query"

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
                return_value={"configurable": {}},
            ),
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            ctx, _ = await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                user_time=datetime.now(UTC),
                stream_id="my-stream-id",
            )

        assert ctx.stream_id == "my-stream-id"

    @pytest.mark.asyncio
    async def test_vfs_session_id_fallback_to_thread_id(self):
        """No vfs_session_id in configurable -> build_agent_config gets thread_id."""
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ) as mock_build_config,
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                user_time=datetime.now(UTC),
            )

        assert mock_build_config.call_args.kwargs["vfs_session_id"] == "t1"

    @pytest.mark.asyncio
    async def test_vfs_session_id_uses_explicit_value(self):
        """Explicit vfs_session_id wins over the thread_id fallback (the `or` branch)."""
        mock_graph = MagicMock(name="executor_graph")

        with (
            patch(
                "app.agents.core.graph_manager.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {}},
            ) as mock_build_config,
            patch(
                "app.helpers.message_helpers.create_system_message",
                return_value=SystemMessage(content="sys"),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
            ),
        ):
            await prepare_executor_execution(
                task="task",
                configurable={
                    "user_id": "u1",
                    "thread_id": "t1",
                    "vfs_session_id": "vfs-pinned",
                },
                user_time=datetime.now(UTC),
            )

        assert mock_build_config.call_args.kwargs["vfs_session_id"] == "vfs-pinned"


# ---------------------------------------------------------------------------
# call_subagent (direct invocation with streaming)
# ---------------------------------------------------------------------------


def _parse_data_frame(chunk: str) -> dict:
    """Parse an SSE data frame, asserting the exact 'data: ...\\n\\n' envelope.

    The strict prefix/suffix check makes the literal envelope bytes load-bearing:
    blanking "data: " or the "\\n\\n" terminator in production turns these red.
    """
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: ") :].strip())


@pytest.mark.unit
class TestCallSubagent:
    @pytest.mark.asyncio
    async def test_happy_path_streams_response_and_terminators(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (AIMessageChunk(content="Response!"), {})))
        mock_ctx = _make_ctx(subagent_graph=mock_graph, agent_name="github_agent")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="List repos",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        response_chunks = [_parse_data_frame(c) for c in chunks if '"response"' in c]
        assert len(response_chunks) == 1
        assert response_chunks[0]["response"] == "Response!"

        # Final nostream frame carries the accumulated complete_message.
        nostream = [c for c in chunks if c.startswith("nostream:")]
        assert len(nostream) == 1
        assert json.loads(nostream[0].replace("nostream: ", ""))["complete_message"] == "Response!"
        assert [c for c in chunks if "DONE" in c] == ["data: [DONE]\n\n"]

    @pytest.mark.asyncio
    async def test_prepare_failure_yields_error_then_done(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(None, "Subagent not found"),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="nonexistent",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        assert len(chunks) == 2
        assert _parse_data_frame(chunks[0])["error"] == "Subagent not found"
        assert chunks[1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_prepare_failure_without_message_uses_fallback_error(self):
        """prepare returning (None, None) still emits an error frame with the fallback
        text and terminates (the `error or ctx is None` guard + fallback string)."""
        mock_graph = MagicMock()
        mock_graph.astream = _empty_astream()
        with patch(
            "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        assert len(chunks) == 2
        assert _parse_data_frame(chunks[0])["error"] == "Failed to prepare subagent execution"
        assert chunks[1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_integration_check_strips_prefix_before_lookup(self):
        """The 'subagent:' prefix is stripped before the integration-check lookup."""
        github = _make_subagent("github", "gh", "github_agent", "github")
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ) as mock_lookup,
            patch(
                "app.agents.core.subagents.subagent_runner.check_subagent_integration",
                new_callable=AsyncMock,
                return_value="nope",
            ) as mock_check,
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="subagent:github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
                skip_integration_check=False,
            ):
                chunks.append(c)

        mock_lookup.assert_called_once_with("github")
        # the resolved subagent.id (not the raw arg) is checked
        mock_check.assert_awaited_once_with("github", "u1")
        assert _parse_data_frame(chunks[0])["error"] == "nope"

    @pytest.mark.asyncio
    async def test_silent_messages_not_streamed(self):
        """Silent message chunks emit no response frame and don't accumulate."""
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="hidden"), {"silent": True}))
        )
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        assert [c for c in chunks if '"response"' in c] == []
        nostream = [c for c in chunks if c.startswith("nostream:")][0]
        assert json.loads(nostream.replace("nostream: ", ""))["complete_message"] == ""

    @pytest.mark.asyncio
    async def test_integration_check_failure_yields_error_then_done(self):
        github = _make_subagent("github", "gh", "github_agent", "github")
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.get_subagent_by_id",
                return_value=github,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.check_subagent_integration",
                new_callable=AsyncMock,
                return_value="Not connected!",
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
                skip_integration_check=False,
            ):
                chunks.append(c)

        assert len(chunks) == 2
        assert _parse_data_frame(chunks[0])["error"] == "Not connected!"
        assert chunks[1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_integration_check_skipped_by_default(self):
        mock_graph = MagicMock()
        mock_graph.astream = _empty_astream()
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.check_subagent_integration",
                new_callable=AsyncMock,
            ) as mock_check,
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            async for _ in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                pass

        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancellation_stops_stream(self):
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("messages", (AIMessageChunk(content="First"), {})),
            ("messages", (AIMessageChunk(content="Second"), {})),
        )
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
                stream_id="s-1",
            ):
                chunks.append(c)

        response_chunks = [_parse_data_frame(c) for c in chunks if '"response"' in c]
        assert len(response_chunks) == 1
        assert response_chunks[0]["response"] == "First"
        # complete_message reflects only the first chunk.
        nostream = [c for c in chunks if c.startswith("nostream:")][0]
        assert json.loads(nostream.replace("nostream: ", ""))["complete_message"] == "First"

    @pytest.mark.asyncio
    async def test_tool_data_streamed_on_agent_updates(self):
        tool_entry = {"name": "search", "args": {}}
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("updates", {"agent": {"messages": []}}))
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[("tc-1", tool_entry)],
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        tool_frames = [_parse_data_frame(c) for c in chunks if "tool_data" in c]
        assert len(tool_frames) == 1
        assert tool_frames[0]["tool_data"] == tool_entry

    @pytest.mark.asyncio
    async def test_non_agent_node_updates_not_streamed(self):
        """Updates from pre-model hook nodes are skipped in the direct stream too."""
        tool_entry = {"name": "search", "args": {}}
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(
            ("updates", {"filter_messages_node": {"messages": []}}),
            ("updates", {"manage_system_prompts_node": {"messages": []}}),
        )
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[("tc-1", tool_entry)],
            ) as mock_extract,
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        mock_extract.assert_not_awaited()
        assert [c for c in chunks if "tool_data" in c] == []

    @pytest.mark.asyncio
    async def test_tool_message_emits_tool_output_frame(self):
        tool_msg = ToolMessage(content="y" * 4000, tool_call_id="tc-7")
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        tool_out = [_parse_data_frame(c) for c in chunks if "tool_output" in c]
        assert len(tool_out) == 1
        assert tool_out[0]["tool_output"]["tool_call_id"] == "tc-7"
        assert len(tool_out[0]["tool_output"]["output"]) == 3000

    @pytest.mark.asyncio
    async def test_finish_task_tool_message_also_emits_response(self):
        """A finish_task ToolMessage yields BOTH a response frame and a tool_output frame,
        and its content becomes the final complete_message."""
        finish = ToolMessage(content="FINAL", tool_call_id="tc-f", name=FINISH_TASK_NAME)
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (finish, {})))
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        response_frames = [_parse_data_frame(c) for c in chunks if '"response"' in c]
        assert len(response_frames) == 1
        assert response_frames[0]["response"] == "FINAL"
        tool_out = [_parse_data_frame(c) for c in chunks if "tool_output" in c]
        assert len(tool_out) == 1
        nostream = [c for c in chunks if c.startswith("nostream:")][0]
        assert json.loads(nostream.replace("nostream: ", ""))["complete_message"] == "FINAL"

    @pytest.mark.asyncio
    async def test_non_finish_task_tool_message_emits_no_response(self):
        """A regular tool result must NOT emit a response frame (finish_task name gate)."""
        tool_msg = ToolMessage(content="hits", tool_call_id="tc-3", name="web_search")
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("messages", (tool_msg, {})))
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        assert [c for c in chunks if '"response"' in c] == []
        # the complete_message is empty (no AI content, finish_task not hit)
        nostream = [c for c in chunks if c.startswith("nostream:")][0]
        assert json.loads(nostream.replace("nostream: ", ""))["complete_message"] == ""

    @pytest.mark.asyncio
    async def test_custom_events_streamed_normalized(self):
        normalized = {"progress": "done", "n": True}
        mock_graph = MagicMock()
        mock_graph.astream = _astream_of(("custom", {"progress": "done"}))
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.normalize_custom_event",
                return_value=normalized,
            ) as mock_norm,
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        mock_norm.assert_called_once_with({"progress": "done"})
        custom_frames = [_parse_data_frame(c) for c in chunks if '"n"' in c]
        assert len(custom_frames) == 1
        assert custom_frames[0] == normalized

    @pytest.mark.asyncio
    async def test_final_nostream_and_done_always_yielded(self):
        mock_graph = MagicMock()
        mock_graph.astream = _empty_astream()
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(UTC),
            ):
                chunks.append(c)

        # No graph events -> empty complete_message, but terminators still emitted.
        nostream = [c for c in chunks if c.startswith("nostream:")]
        assert len(nostream) == 1
        assert json.loads(nostream[0].replace("nostream: ", ""))["complete_message"] == ""
        assert chunks[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# subagent_helpers.py — build_subagent_system_prompt (support coverage)
# ---------------------------------------------------------------------------


from app.agents.core.subagents.subagent_helpers import (  # noqa: E402
    build_subagent_system_prompt,
    create_agent_context_message,
    create_subagent_system_message,
)


@pytest.mark.unit
class TestBuildSubagentSystemPrompt:
    @pytest.mark.asyncio
    async def test_returns_static_base_prompt_without_user_metadata(self):
        """The static subagent prompt must be byte-identical across users.

        Provider metadata (usernames, emails) flows through the dynamic
        context message — see create_agent_context_message — so the static
        prefix the LLM receives stays cacheable.
        """
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"Username": "testuser"},
            ) as mock_meta,
        ):
            result = await build_subagent_system_prompt("github", user_id="u1")

        assert "You are the GitHub agent." in result
        assert "USER CONTEXT FOR GITHUB" not in result
        assert "testuser" not in result
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_metadata_when_no_user_id(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
        ):
            result = await build_subagent_system_prompt("github")

        mock_meta.assert_not_awaited()
        assert "You are the GitHub agent." in result

    @pytest.mark.asyncio
    async def test_integration_not_found_uses_custom_prompt(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
            return_value=None,
        ):
            result = await build_subagent_system_prompt("custom_tool_123")

        # Should return the CUSTOM_MCP_SUBAGENT_PROMPT or the base_system_prompt
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_base_system_prompt_override(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await build_subagent_system_prompt(
                "github", base_system_prompt="Custom prompt"
            )

        assert result == "Custom prompt"

    @pytest.mark.asyncio
    async def test_metadata_fetch_error_handled(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB down"),
            ),
        ):
            result = await build_subagent_system_prompt("github", user_id="u1")

        # Should not raise, returns prompt without metadata
        assert "You are the GitHub agent." in result

    @pytest.mark.asyncio
    async def test_empty_metadata_no_context_injected(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await build_subagent_system_prompt("github", user_id="u1")

        assert "USER CONTEXT" not in result


# ---------------------------------------------------------------------------
# create_subagent_system_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubagentSystemMessage:
    @pytest.mark.asyncio
    async def test_returns_system_message(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.build_subagent_system_prompt",
            new_callable=AsyncMock,
            return_value="Test prompt",
        ):
            result = await create_subagent_system_message(
                integration_id="github",
                agent_name="github_agent",
            )

        assert isinstance(result, SystemMessage)
        assert result.content == "Test prompt"


# ---------------------------------------------------------------------------
# create_agent_context_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAgentContextMessage:
    @pytest.mark.asyncio
    async def test_returns_system_message_without_clock(self):
        """The clock intentionally does NOT live in the dynamic-context
        system message. It rides in a HumanMessage built by
        ``build_current_time_message`` so the ``system_instruction`` prefix
        stays stable across minute boundaries.
        """
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={"user_name": "Alice"},
            )

        assert isinstance(result, SystemMessage)
        assert "Current UTC Time:" not in result.content
        assert "User Local Time:" not in result.content

    @pytest.mark.asyncio
    async def test_includes_user_name(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={"user_name": "Bob"},
            )

        assert "User Name: Bob" in result.content

    @pytest.mark.asyncio
    async def test_includes_user_timezone(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={
                    "user_time": "2025-06-15T10:30:00+05:30",
                },
            )

        assert "User Timezone Offset: +05:30" in result.content
        # Local clock moved out of the dynamic system message. It's emitted
        # as a HumanMessage by ``build_current_time_message`` instead.
        assert "User Local Time:" not in result.content

    @pytest.mark.asyncio
    async def test_memories_included(self):
        mem = MagicMock()
        mem.content = "User prefers dark mode"
        mock_results = MagicMock()
        mock_results.memories = [mem]

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
                query="preferences",
            )

        assert "User prefers dark mode" in result.content

    @pytest.mark.asyncio
    async def test_skills_included(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="SKILLS:\n- search_github",
            ),
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
                subagent_id="github_agent",
            )

        assert "SKILLS:" in result.content
        assert "search_github" in result.content

    @pytest.mark.asyncio
    async def test_no_memories_without_user_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            await create_agent_context_message(
                configurable={},
                query="hello",
            )

        mock_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_memories_without_query(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            await create_agent_context_message(
                configurable={},
                user_id="u1",
            )

        mock_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_memory_error_handled(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mem error"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
                query="test",
            )

        # Should not raise; just won't have memories
        assert isinstance(result, SystemMessage)

    @pytest.mark.asyncio
    async def test_skills_error_handled(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                side_effect=RuntimeError("skills error"),
            ),
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
            )

        assert isinstance(result, SystemMessage)

    @pytest.mark.asyncio
    async def test_user_time_z_offset(self):
        """Z timezone offset should be converted to +00:00."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={"user_time": "2025-06-15T10:30:00Z"},
            )

        # Z should be converted to +00:00
        assert "User Timezone Offset: +00:00" in result.content

    @pytest.mark.asyncio
    async def test_invalid_user_time_handled(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={"user_time": "not-a-valid-time"},
            )

        # Should not raise; clock doesn't live here any more.
        assert isinstance(result, SystemMessage)

    @pytest.mark.asyncio
    async def test_dynamic_context_marker(self):
        """Context messages carry ``dynamic_context`` in additional_kwargs so
        manage_system_prompts_node can keep only the latest one per run. The
        legacy ``memory_message`` key is still present for back-compat with
        older persisted state."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(configurable={})

        assert result.additional_kwargs.get("dynamic_context") is True
        assert result.additional_kwargs.get("memory_message") is True
