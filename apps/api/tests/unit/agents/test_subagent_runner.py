"""Unit tests for subagent_runner.py and subagent_helpers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
import pytest

from app.agents.core.graph_manager import GraphUnavailableError
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    build_initial_messages,
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.constants.log_tags import LogTag
from app.constants.skills import EXECUTOR_SUBAGENT_ID
from app.helpers.message_helpers import (
    BACKGROUND_EXECUTION_BANNER,
    EXECUTOR_CONNECTED_INTEGRATIONS_HEADER,
)
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


def _stub_integration(name: str = "GitHub", provider: str | None = "github") -> MagicMock:
    """Integration-shaped fixture for `get_integration_by_id` (used by the
    dynamic-context provider-metadata and custom-instructions blocks).
    """
    integration = MagicMock()
    integration.name = name
    integration.provider = provider
    return integration


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------


class TestBuildInitialMessages:
    @pytest.mark.asyncio
    async def test_returns_four_messages(self):
        """Shape is [static, dynamic_context, time_msg, human_task].

        The time HumanMessage is separated from the user task so minute
        ticks don't reset the ``system_instruction`` cache boundary.
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
                configurable={"user_timezone": "Asia/Kolkata"},
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
    async def test_human_message_has_visible_to(self):
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

        # Task HumanMessage is now at index 3 (after the time_msg at 2)
        human_msg = result[3]
        assert "my_agent" in human_msg.additional_kwargs["visible_to"]

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

        kwargs = mock_ctx.call_args.kwargs
        assert kwargs["query"] == "my search query"

    @pytest.mark.asyncio
    async def test_retrieval_query_overridden(self):
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

        kwargs = mock_ctx.call_args.kwargs
        assert kwargs["query"] == "original query"

    @pytest.mark.asyncio
    async def test_user_id_and_subagent_id_passed(self):
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
            )

        kwargs = mock_ctx.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["subagent_id"] == "github_agent"


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
            )

        assert error is None
        # The human message (last in initial_state["messages"]) should have the hint
        human_msg = ctx.initial_state["messages"][-1]
        assert "DIRECT EXECUTION HINT" in human_msg.content

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
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
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
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
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
                "app.agents.core.subagents.subagent_runner.create_agent_context_message",
                new_callable=AsyncMock,
                return_value=SystemMessage(content="ctx"),
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


from app.agents.core.subagents.subagent_helpers import (  # noqa: E402
    _fetch_instructions_block,
    _fetch_provider_metadata_block,
    build_subagent_system_prompt,
    create_agent_context_message,
    create_subagent_system_message,
)
from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT  # noqa: E402


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
            ) as mock_get,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"Username": "testuser"},
            ) as mock_meta,
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await build_subagent_system_prompt("github")

        assert result == "You are the GitHub agent."
        assert "USER CONTEXT FOR GITHUB" not in result
        assert "testuser" not in result
        mock_get.assert_called_once_with("github")
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integration_not_found_uses_custom_prompt(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ) as mock_get:
            result = await build_subagent_system_prompt("custom_tool_123")

        assert result == CUSTOM_MCP_SUBAGENT_PROMPT
        mock_get.assert_called_once_with("custom_tool_123")

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
        with (
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id"
            ) as mock_get,
        ):
            assert await build_subagent_system_prompt("") == ""

        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Integration not found", integration_id=""
        )
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_blank_integration_id_returns_base_system_prompt(self):
        with (
            patch("app.agents.core.subagents.subagent_helpers.log"),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_subagent_by_id"
            ) as mock_get,
        ):
            result = await build_subagent_system_prompt("", base_system_prompt="Override")

        assert result == "Override"
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_config_system_prompt_returns_empty(self):
        integration = _make_integration("github")
        integration.config.system_prompt = ""

        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=integration,
        ):
            result = await build_subagent_system_prompt("github")

        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_config_system_prompt_falls_back_to_base(self):
        integration = _make_integration("github")
        integration.config.system_prompt = ""

        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=integration,
        ):
            result = await build_subagent_system_prompt("github", base_system_prompt="Override")

        assert result == "Override"

    @pytest.mark.asyncio
    async def test_empty_base_prompt_falls_back_to_custom_mcp_prompt(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ):
            result = await build_subagent_system_prompt("custom_tool_123", base_system_prompt="")

        assert result == CUSTOM_MCP_SUBAGENT_PROMPT


# ---------------------------------------------------------------------------
# create_subagent_system_message
# ---------------------------------------------------------------------------


class TestCreateSubagentSystemMessage:
    @pytest.mark.asyncio
    async def test_wraps_integration_prompt_in_system_message(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=_make_integration("github"),
        ) as mock_get:
            result = await create_subagent_system_message(integration_id="github")

        assert isinstance(result, SystemMessage)
        assert result.content == "You are the GitHub agent."
        mock_get.assert_called_once_with("github")

    @pytest.mark.asyncio
    async def test_unknown_integration_falls_back_to_custom_prompt(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ):
            result = await create_subagent_system_message(integration_id="custom_tool_123")

        assert result.content == CUSTOM_MCP_SUBAGENT_PROMPT

    @pytest.mark.asyncio
    async def test_base_system_prompt_passed_through(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_subagent_by_id",
            return_value=None,
        ):
            result = await create_subagent_system_message(
                integration_id="custom_tool_123", base_system_prompt="Override"
            )

        assert result.content == "Override"

    @pytest.mark.asyncio
    async def test_blank_integration_id_yields_empty_content(self):
        with patch("app.agents.core.subagents.subagent_helpers.log"):
            result = await create_subagent_system_message(integration_id="")

        assert result.content == ""


# ---------------------------------------------------------------------------
# _fetch_provider_metadata_block
# ---------------------------------------------------------------------------


class TestFetchProviderMetadataBlock:
    @pytest.mark.asyncio
    async def test_empty_without_integration_id(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_integration_by_id"
        ) as mock_get:
            result = await _fetch_provider_metadata_block("", "u1")

        assert result == ""
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_without_user_id(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_integration_by_id"
        ) as mock_get:
            result = await _fetch_provider_metadata_block("github", None)

        assert result == ""
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_when_integration_unknown(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        assert result == ""
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_when_integration_has_no_provider(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", provider=None),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        assert result == ""
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prefetched_metadata_skips_lookup(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ) as mock_get,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
        ):
            result = await _fetch_provider_metadata_block(
                "github", "u1", metadata={"login": "octocat"}
            )

        assert result == "\n\nUSER CONTEXT FOR GITHUB:\n- login: octocat\n"
        mock_get.assert_called_once_with("github")
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prefetched_empty_metadata_returns_empty(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
        ):
            result = await _fetch_provider_metadata_block("github", "u1", metadata={})

        assert result == ""
        mock_meta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetches_metadata_with_exact_args_and_formats(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"login": "octocat", "name": "Octo Cat"},
            ) as mock_meta,
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        mock_meta.assert_awaited_once_with("u1", "github")
        assert result == "\n\nUSER CONTEXT FOR GITHUB:\n- login: octocat\n- name: Octo Cat\n"

    @pytest.mark.asyncio
    async def test_returns_empty_when_fetch_returns_none(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_fetch_returns_empty_dict(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_error_logged_and_suppressed(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await _fetch_provider_metadata_block("github", "u1")

        assert result == ""
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Failed to fetch provider metadata",
            provider="github",
            user_id="u1",
            error_type="RuntimeError",
            error="boom",
        )


# ---------------------------------------------------------------------------
# _fetch_instructions_block
# ---------------------------------------------------------------------------


class TestFetchInstructionsBlock:
    @pytest.mark.asyncio
    async def test_empty_without_integration_id(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_instructions",
            new_callable=AsyncMock,
        ) as mock_instructions:
            result = await _fetch_instructions_block("", "u1")

        assert result == ""
        mock_instructions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_without_user_id(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.get_instructions",
            new_callable=AsyncMock,
        ) as mock_instructions:
            result = await _fetch_instructions_block("slack", None)

        assert result == ""
        mock_instructions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_instructions(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id"
            ) as mock_get,
        ):
            result = await _fetch_instructions_block("slack", "u1")

        assert result == ""
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_instructions_blank(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id"
            ) as mock_get,
        ):
            result = await _fetch_instructions_block("slack", "u1")

        assert result == ""
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_error_logged_and_suppressed(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await _fetch_instructions_block("slack", "u1")

        assert result == ""
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Failed to fetch custom instructions",
            integration_id="slack",
            user_id="u1",
            error_type="RuntimeError",
            error="boom",
        )

    @pytest.mark.asyncio
    async def test_formats_block_with_integration_name(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="focus on #eng",
            ) as mock_instructions,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("Slack"),
            ) as mock_get,
        ):
            result = await _fetch_instructions_block("slack", "u1")

        mock_instructions.assert_awaited_once_with("u1", "slack")
        mock_get.assert_called_once_with("slack")
        assert result == (
            "\n\nCUSTOM INSTRUCTIONS FOR SLACK (set by the user — honor these):\n"
            "focus on #eng\n"
        )

    @pytest.mark.asyncio
    async def test_strips_instruction_whitespace(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="  focus on #eng  ",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("Slack"),
            ),
        ):
            result = await _fetch_instructions_block("slack", "u1")

        assert result == (
            "\n\nCUSTOM INSTRUCTIONS FOR SLACK (set by the user — honor these):\n"
            "focus on #eng\n"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_integration_id_label(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="focus on #eng",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=None,
            ),
        ):
            result = await _fetch_instructions_block("slack", "u1")

        assert result == (
            "\n\nCUSTOM INSTRUCTIONS FOR SLACK (set by the user — honor these):\n"
            "focus on #eng\n"
        )


# ---------------------------------------------------------------------------
# create_agent_context_message
# ---------------------------------------------------------------------------


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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                    "user_timezone": "Asia/Kolkata",
                },
            )

        assert "User Timezone: Asia/Kolkata" in result.content
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="SKILLS:\n- search_github",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mem error"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
                query="test",
            )

        # Should not raise; just won't have memories
        assert result.content == ""
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Error retrieving memories for subagent",
            user_id="u1",
            error_type="RuntimeError",
            error="mem error",
        )

    @pytest.mark.asyncio
    async def test_skills_error_handled(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                side_effect=RuntimeError("skills error"),
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
            )

        assert result.content == ""
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Error injecting installable skills",
            user_id="u1",
            error_type="RuntimeError",
            error="skills error",
        )

    @pytest.mark.asyncio
    async def test_prefetched_empty_skills_add_no_section(self):
        """An explicitly prefetched empty skills string must not inject a
        blank skills section (``skills_text or ""`` fallback)."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
            ) as mock_skills,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", skills_text=""
            )

        assert result.content == ""
        mock_skills.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_timezone_offset(self):
        """A fixed-offset home zone is rendered verbatim as the timezone line."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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
                configurable={"user_timezone": "+05:30"},
            )

        assert "User Timezone: +05:30" in result.content

    @pytest.mark.asyncio
    async def test_no_timezone_line_without_user_timezone(self):
        """With no home zone in the config, no timezone line is added."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await create_agent_context_message(
                configurable={},
            )

        assert isinstance(result, SystemMessage)
        assert "User Timezone:" not in result.content

    @pytest.mark.asyncio
    async def test_dynamic_context_marker(self):
        """Context messages carry ``dynamic_context`` in additional_kwargs so
        manage_system_prompts_node can keep only the latest one per run. The
        legacy ``memory_message`` key is still present for back-compat with
        older persisted state."""
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
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

    @pytest.mark.asyncio
    async def test_background_execution_banner_leads(self):
        """The background banner must lead the message so the executor never
        asks clarifying questions when no human is on the other end."""
        result = await create_agent_context_message(
            configurable={"execution_mode": "background", "user_name": "Bob"},
        )

        assert result.content == f"{BACKGROUND_EXECUTION_BANNER}\nUser Name: Bob"

    @pytest.mark.asyncio
    async def test_interactive_mode_has_no_banner(self):
        result = await create_agent_context_message(
            configurable={"execution_mode": "interactive", "user_name": "Bob"},
        )

        assert "BACKGROUND EXECUTION" not in result.content

    @pytest.mark.asyncio
    async def test_active_todo_banner_included(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers._build_active_todo_banner",
                new_callable=AsyncMock,
                return_value="TODO BANNER",
            ) as mock_banner,
        ):
            result = await create_agent_context_message(
                configurable={"active_todo_id": "todo-1"}, user_id="u1"
            )

        assert result.content == "TODO BANNER"
        mock_banner.assert_awaited_once_with("u1", "todo-1")

    @pytest.mark.asyncio
    async def test_active_todo_banner_omitted_when_empty(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers._build_active_todo_banner",
                new_callable=AsyncMock,
                return_value="",
            ) as mock_banner,
        ):
            result = await create_agent_context_message(
                configurable={"active_todo_id": "todo-1"}, user_id="u1"
            )

        assert result.content == ""
        mock_banner.assert_awaited_once_with("u1", "todo-1")

    @pytest.mark.asyncio
    async def test_active_todo_banner_requires_user_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers._build_active_todo_banner",
                new_callable=AsyncMock,
            ) as mock_banner,
        ):
            result = await create_agent_context_message(
                configurable={"active_todo_id": "todo-1"}
            )

        assert result.content == ""
        mock_banner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_banner_included(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.build_workspace_session_banner",
            return_value="SESSION BANNER",
        ) as mock_banner:
            result = await create_agent_context_message(
                configurable={"vfs_session_id": "sess-1", "thread_id": "thread-1"}
            )

        assert result.content == "SESSION BANNER"
        mock_banner.assert_called_once_with("sess-1")

    @pytest.mark.asyncio
    async def test_no_session_banner_without_vfs_session_id(self):
        with patch(
            "app.agents.core.subagents.subagent_helpers.build_workspace_session_banner",
        ) as mock_banner:
            result = await create_agent_context_message(
                configurable={"thread_id": "thread-1"}
            )

        assert result.content == ""
        mock_banner.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_id_falls_back_to_configurable(self):
        mock_results = MagicMock()
        mock_results.memories = []

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=mock_results,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            await create_agent_context_message(configurable={"user_id": "u-cfg"}, query="q")

        mock_search.assert_awaited_once_with("u-cfg", "q", limit=5)

    @pytest.mark.asyncio
    async def test_prefetched_memories_skip_recall(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", query="q", memories_text="PREFETCHED"
            )

        assert result.content == "PREFETCHED"
        assert "Based on our previous conversations" not in result.content
        mock_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_recall_adds_no_memories_section(self):
        mock_results = MagicMock()
        mock_results.memories = []

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", query="q"
            )

        assert result.content == ""
        mock_log.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_memories_exact_format_and_recall_args(self):
        m1 = MagicMock()
        m1.content = "first"
        m2 = MagicMock()
        m2.content = "second"
        mock_results = MagicMock()
        mock_results.memories = [m1, m2]

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=mock_results,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", query="q"
            )

        mock_search.assert_awaited_once_with("u1", "q", limit=5)
        assert result.content == "\n\nBased on our previous conversations:\n- first\n- second"
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Added memories to subagent context", memory_count=2
        )

    @pytest.mark.asyncio
    async def test_prefetched_skills_skip_fetch(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
            ) as mock_skills,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", skills_text="SKILLS TEXT"
            )

        assert result.content == "\n\nSKILLS TEXT"
        mock_skills.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skills_fetch_defaults_agent_name_to_executor(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ) as mock_skills,
        ):
            await create_agent_context_message(configurable={}, user_id="u1")

        mock_skills.assert_awaited_once_with(
            user_id="u1", agent_name=EXECUTOR_SUBAGENT_ID
        )

    @pytest.mark.asyncio
    async def test_skills_fetch_uses_subagent_id_as_agent_name(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ) as mock_skills,
            patch(
                "app.agents.core.subagents.subagent_helpers.target_to_subagent",
                return_value="github",
            ),
            patch(
                "app.agents.workspace.system_docs.integration_skills_block",
                return_value="",
            ),
        ):
            await create_agent_context_message(configurable={}, user_id="u1", subagent_id="github_agent")

        mock_skills.assert_awaited_once_with(user_id="u1", agent_name="github_agent")

    @pytest.mark.asyncio
    async def test_integration_skills_block_appended_after_fetched_skills(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="SKILLS A",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.target_to_subagent",
                return_value="github",
            ) as mock_map,
            patch(
                "app.agents.workspace.system_docs.integration_skills_block",
                return_value="INTEGRATION BLOCK",
            ) as mock_block,
            patch("app.agents.core.subagents.subagent_helpers.log") as mock_log,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", subagent_id="github_agent"
            )

        mock_map.assert_called_once_with("github_agent")
        mock_block.assert_called_once_with("github")
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Injected installable skills", agent_name="github_agent"
        )
        assert result.content == "\n\nSKILLS A\n\nINTEGRATION BLOCK"

    @pytest.mark.asyncio
    async def test_integration_skills_block_alone_without_user_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ) as mock_search,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
            ) as mock_skills,
            patch(
                "app.agents.core.subagents.subagent_helpers.target_to_subagent",
                return_value="github",
            ),
            patch(
                "app.agents.workspace.system_docs.integration_skills_block",
                return_value="INTEGRATION BLOCK",
            ),
        ):
            result = await create_agent_context_message(
                configurable={}, subagent_id="github_agent"
            )

        assert result.content == "\n\nINTEGRATION BLOCK"
        mock_search.assert_not_awaited()
        mock_skills.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integration_skills_block_omitted_when_empty(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="SKILLS A",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.target_to_subagent",
                return_value="github",
            ),
            patch(
                "app.agents.workspace.system_docs.integration_skills_block",
                return_value="",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", subagent_id="github_agent"
            )

        assert result.content == "\n\nSKILLS A"

    @pytest.mark.asyncio
    async def test_connected_integrations_manifest_included(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.build_connected_integrations_manifest",
                new_callable=AsyncMock,
                return_value="MANIFEST",
            ) as mock_manifest,
        ):
            result = await create_agent_context_message(
                configurable={"user_name": "Alice"},
                user_id="u1",
                include_connected_integrations=True,
            )

        mock_manifest.assert_awaited_once_with(
            "u1", header=EXECUTOR_CONNECTED_INTEGRATIONS_HEADER
        )
        assert result.content == "User Name: Alice\nMANIFEST"

    @pytest.mark.asyncio
    async def test_connected_integrations_skipped_by_default(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.build_connected_integrations_manifest",
                new_callable=AsyncMock,
            ) as mock_manifest,
        ):
            await create_agent_context_message(configurable={}, user_id="u1")

        mock_manifest.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connected_integrations_requires_user_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.build_connected_integrations_manifest",
                new_callable=AsyncMock,
            ) as mock_manifest,
        ):
            await create_agent_context_message(
                configurable={}, include_connected_integrations=True
            )

        mock_manifest.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_metadata_section_included(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ) as mock_get,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"login": "octocat"},
            ) as mock_meta,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", integration_id="github"
            )

        mock_get.assert_called_once_with("github")
        mock_meta.assert_awaited_once_with("u1", "github")
        assert result.content == "\n\nUSER CONTEXT FOR GITHUB:\n- login: octocat\n"

    @pytest.mark.asyncio
    async def test_prefetched_provider_metadata_skips_lookup(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_meta,
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await create_agent_context_message(
                configurable={},
                user_id="u1",
                integration_id="github",
                provider_metadata={"login": "octocat"},
            )

        mock_meta.assert_not_awaited()
        assert result.content == "\n\nUSER CONTEXT FOR GITHUB:\n- login: octocat\n"

    @pytest.mark.asyncio
    async def test_instructions_section_included(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("Slack", provider=None),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="  focus on #eng  ",
            ) as mock_instructions,
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", integration_id="slack"
            )

        mock_instructions.assert_awaited_once_with("u1", "slack")
        assert result.content == (
            "\n\nCUSTOM INSTRUCTIONS FOR SLACK (set by the user — honor these):\n"
            "focus on #eng\n"
        )

    @pytest.mark.asyncio
    async def test_instructions_fall_back_to_subagent_id(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="instructions text",
            ) as mock_instructions,
            patch(
                "app.agents.core.subagents.subagent_helpers.target_to_subagent",
                return_value="github",
            ),
            patch(
                "app.agents.workspace.system_docs.integration_skills_block",
                return_value="",
            ),
        ):
            result = await create_agent_context_message(
                configurable={}, user_id="u1", subagent_id="github_agent"
            )

        mock_instructions.assert_awaited_once_with("u1", "github_agent")
        assert result.content == (
            "\n\nCUSTOM INSTRUCTIONS FOR GITHUB_AGENT (set by the user — honor these):\n"
            "instructions text\n"
        )

    @pytest.mark.asyncio
    async def test_sections_joined_in_exact_order(self):
        """Static prefix parts, then memories, skills, provider metadata, and
        custom instructions — in that order, with no separators between the
        fetched sections beyond their own leading newlines."""
        m1 = MagicMock()
        m1.content = "mem1"
        mock_results = MagicMock()
        mock_results.memories = [m1]

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.memory_engine.recall",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_available_skills_text",
                new_callable=AsyncMock,
                return_value="SKILLS TEXT",
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=_stub_integration("GitHub", "github"),
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"login": "octocat"},
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_instructions",
                new_callable=AsyncMock,
                return_value="instructions text",
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await create_agent_context_message(
                configurable={"user_name": "Alice", "user_timezone": "Asia/Kolkata"},
                user_id="u1",
                query="q",
                integration_id="github",
            )

        expected = (
            "User Name: Alice\nUser Timezone: Asia/Kolkata"
            "\n\nBased on our previous conversations:\n- mem1"
            "\n\nSKILLS TEXT"
            "\n\nUSER CONTEXT FOR GITHUB:\n- login: octocat\n"
            "\n\nCUSTOM INSTRUCTIONS FOR GITHUB (set by the user — honor these):\n"
            "instructions text\n"
        )
        assert result.content == expected

    @pytest.mark.asyncio
    async def test_empty_config_yields_empty_content(self):
        result = await create_agent_context_message(configurable={})

        assert result.content == ""
