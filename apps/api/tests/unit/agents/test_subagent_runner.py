"""Unit tests for subagent_runner.py and subagent_helpers.py."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    build_initial_messages,
    call_subagent,
    check_subagent_integration,
    execute_subagent_stream,
    get_subagent_by_id,
    get_subagent_integrations,
    prepare_executor_execution,
    prepare_subagent_execution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_integration(
    integration_id: str = "github",
    short_name: str = "gh",
    has_subagent: bool = True,
    agent_name: str = "github_agent",
    provider: str = "github",
):
    """Create a mock OAuthIntegration with subagent_config."""
    subagent_cfg = MagicMock()
    subagent_cfg.has_subagent = has_subagent
    subagent_cfg.agent_name = agent_name
    subagent_cfg.system_prompt = "You are the GitHub agent."

    integration = MagicMock()
    integration.id = integration_id
    integration.name = integration_id.title()
    integration.short_name = short_name
    integration.provider = provider
    integration.subagent_config = subagent_cfg
    return integration


def _make_integration_no_subagent(integration_id: str = "stripe"):
    integration = MagicMock()
    integration.id = integration_id
    integration.name = integration_id.title()
    integration.short_name = None
    integration.subagent_config = None
    return integration


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


FAKE_INTEGRATIONS = [
    _make_integration("github", "gh", True, "github_agent"),
    _make_integration("gmail", "gmail", True, "gmail_agent"),
    _make_integration_no_subagent("stripe"),
]


# ---------------------------------------------------------------------------
# get_subagent_integrations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSubagentIntegrations:
    def test_filters_integrations_with_subagent(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_integrations()

        assert len(result) == 2
        ids = [i.id for i in result]
        assert "github" in ids
        assert "gmail" in ids
        assert "stripe" not in ids

    def test_empty_integrations(self):
        with patch("app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS", []):
            assert get_subagent_integrations() == []


# ---------------------------------------------------------------------------
# get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSubagentById:
    def test_find_by_id(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("github")
        assert result is not None
        assert result.id == "github"

    def test_find_by_short_name(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("gh")
        assert result is not None
        assert result.id == "github"

    def test_case_insensitive(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("GITHUB")
        assert result is not None

    def test_not_found(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("nonexistent")
        assert result is None

    def test_integration_without_subagent_not_returned(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("stripe")
        assert result is None

    def test_strips_whitespace(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
            FAKE_INTEGRATIONS,
        ):
            result = get_subagent_by_id("  github  ")
        assert result is not None


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildInitialMessages:
    @pytest.mark.asyncio
    async def test_returns_three_messages(self):
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
                configurable={"user_time": "2025-01-01T00:00:00Z"},
                task="Do the thing",
            )

        assert len(result) == 3
        assert result[0] is sys_msg
        assert result[1] is ctx_msg
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "Do the thing"

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

        human_msg = result[2]
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
# prepare_subagent_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareSubagentExecution:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_graph = MagicMock(name="subagent_graph")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "github_conv-1"}},
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
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="github",
                task="List my repos",
                user={"user_id": "u1", "email": "t@t.com", "name": "T"},
                user_time=datetime.now(timezone.utc),
                conversation_id="conv-1",
            )

        assert error is None
        assert ctx is not None
        assert ctx.agent_name == "github_agent"
        assert ctx.integration_id == "github"
        assert ctx.subagent_graph is mock_graph

    @pytest.mark.asyncio
    async def test_subagent_not_found_error(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="nonexistent",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(timezone.utc),
                conversation_id="conv-1",
            )

        assert ctx is None
        assert error is not None
        assert "not found" in error

    @pytest.mark.asyncio
    async def test_graph_not_available_error(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="github",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(timezone.utc),
                conversation_id="conv-1",
            )

        assert ctx is None
        assert "not available" in error

    @pytest.mark.asyncio
    async def test_strips_subagent_prefix(self):
        """subagent_id like 'subagent:github' should resolve to 'github'."""
        mock_graph = MagicMock(name="subagent_graph")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.providers.aget",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.build_agent_config",
                return_value={"configurable": {"thread_id": "t"}},
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
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            ctx, error = await prepare_subagent_execution(
                subagent_id="subagent:github",
                task="task",
                user={"user_id": "u1"},
                user_time=datetime.now(timezone.utc),
                conversation_id="conv-1",
            )

        assert error is None
        assert ctx is not None


# ---------------------------------------------------------------------------
# execute_subagent_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteSubagentStream:
    @pytest.mark.asyncio
    async def test_accumulates_ai_content(self):
        chunk1 = AIMessageChunk(content="Hello ")
        chunk2 = AIMessageChunk(content="world")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk1, {}))
            yield ("messages", (chunk2, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream

        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert result == "Hello world"

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

        assert result == "Task completed"  # default when no content

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

        assert result == "Task completed"

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
    async def test_tool_message_content_truncated(self):
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
        assert len(output) == 3000

    @pytest.mark.asyncio
    async def test_updates_emit_tool_data(self):
        """Updates stream mode should extract tool entries and emit them."""
        tool_entry = {"name": "web_search", "args": {"q": "test"}}
        stream_writer = MagicMock()

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"node1": {"messages": []}})

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
        assert result == "Task completed"

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

        # Only first chunk processed before cancellation on the second
        assert result == "First "

    @pytest.mark.asyncio
    async def test_non_tuple_events_skipped(self):
        """Events with length != 2 should be silently skipped."""

        async def _fake_astream(*args, **kwargs):
            yield ("a", "b", "c")  # 3-tuple, should be skipped
            yield ("messages", (AIMessageChunk(content="ok"), {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        ctx = _make_ctx(subagent_graph=mock_graph)

        with patch("app.agents.core.subagents.subagent_runner.log"):
            result = await execute_subagent_stream(ctx)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_integration_metadata_passed_to_extract(self):
        metadata = {"icon_url": "https://icon.png", "name": "Custom MCP"}

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"node": {"messages": []}})

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
    async def test_not_connected_returns_message(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.check_integration_status",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await check_subagent_integration("github", "u1")
        assert result is not None
        assert "not connected" in result

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        with patch(
            "app.agents.core.subagents.subagent_runner.check_integration_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            with patch("app.agents.core.subagents.subagent_runner.log"):
                result = await check_subagent_integration("github", "u1")
        assert result is None


# ---------------------------------------------------------------------------
# prepare_executor_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareExecutorExecution:
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
                user_time=datetime.now(timezone.utc),
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
            return_value=None,
        ):
            ctx, error = await prepare_executor_execution(
                task="task",
                configurable={"user_id": "u1", "thread_id": "t1"},
                user_time=datetime.now(timezone.utc),
            )

        assert ctx is None
        assert "not available" in error

    @pytest.mark.asyncio
    async def test_direct_handoff_hint_injected(self):
        """When tool_category matches a known subagent, a hint is injected."""
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
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
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
                user_time=datetime.now(timezone.utc),
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
                user_time=datetime.now(timezone.utc),
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
                user_time=datetime.now(timezone.utc),
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
                user_time=datetime.now(timezone.utc),
            )

        call_kwargs = mock_build_config.call_args.kwargs
        assert call_kwargs["vfs_session_id"] == "t1"


# ---------------------------------------------------------------------------
# call_subagent (direct invocation with streaming)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallSubagent:
    @pytest.mark.asyncio
    async def test_happy_path_streaming(self):
        chunk = AIMessageChunk(content="Response!")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream

        mock_ctx = _make_ctx(subagent_graph=mock_graph, agent_name="github_agent")

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="List repos",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(timezone.utc),
            ):
                chunks.append(c)

        # Should have: response chunk, nostream complete_message, DONE
        response_chunks = [c for c in chunks if '"response"' in c]
        assert len(response_chunks) == 1
        assert "Response!" in response_chunks[0]

        done_chunks = [c for c in chunks if "DONE" in c]
        assert len(done_chunks) == 1

    @pytest.mark.asyncio
    async def test_prepare_failure_yields_error(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(None, "Subagent not found"),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="nonexistent",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(timezone.utc),
            ):
                chunks.append(c)

        assert len(chunks) == 2
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert "error" in parsed
        assert "DONE" in chunks[1]

    @pytest.mark.asyncio
    async def test_integration_check_failure_yields_error(self):
        with (
            patch(
                "app.agents.core.subagents.subagent_runner.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.check_subagent_integration",
                new_callable=AsyncMock,
                return_value="Not connected!",
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(timezone.utc),
                skip_integration_check=False,
            ):
                chunks.append(c)

        assert len(chunks) == 2
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert "Not connected!" in parsed["error"]

    @pytest.mark.asyncio
    async def test_integration_check_skipped_by_default(self):
        """skip_integration_check=True (default) means no check_integration_status call."""

        async def _fake_astream(*args, **kwargs):
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
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
            patch("app.agents.core.subagents.subagent_runner.log"),
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
                user_time=datetime.now(timezone.utc),
            ):
                pass

        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancellation_stops_stream(self):
        chunk1 = AIMessageChunk(content="First")
        chunk2 = AIMessageChunk(content="Second")

        async def _fake_astream(*args, **kwargs):
            yield ("messages", (chunk1, {}))
            yield ("messages", (chunk2, {}))

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
            patch(
                "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ),
            patch(
                "app.agents.core.subagents.subagent_runner.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            chunks = []
            async for c in call_subagent(
                subagent_id="github",
                query="hello",
                user={"user_id": "u1"},
                conversation_id="conv-1",
                user_time=datetime.now(timezone.utc),
                stream_id="s-1",
            ):
                chunks.append(c)

        response_chunks = [c for c in chunks if '"response"' in c]
        # Only first chunk should be there
        assert len(response_chunks) == 1
        assert "First" in response_chunks[0]

    @pytest.mark.asyncio
    async def test_tool_data_streamed(self):
        tool_entry = {"name": "search", "args": {}}

        async def _fake_astream(*args, **kwargs):
            yield ("updates", {"node": {"messages": []}})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
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
                user_time=datetime.now(timezone.utc),
            ):
                chunks.append(c)

        tool_chunks = [c for c in chunks if "tool_data" in c]
        assert len(tool_chunks) == 1

    @pytest.mark.asyncio
    async def test_custom_events_streamed(self):
        async def _fake_astream(*args, **kwargs):
            yield ("custom", {"progress": "done"})

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
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
                user_time=datetime.now(timezone.utc),
            ):
                chunks.append(c)

        custom_chunks = [c for c in chunks if "progress" in c]
        assert len(custom_chunks) == 1

    @pytest.mark.asyncio
    async def test_final_nostream_and_done_always_yielded(self):
        async def _fake_astream(*args, **kwargs):
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_graph = MagicMock()
        mock_graph.astream = _fake_astream
        mock_ctx = _make_ctx(subagent_graph=mock_graph)

        with (
            patch(
                "app.agents.core.subagents.subagent_runner.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(mock_ctx, None),
            ),
            patch("app.agents.core.subagents.subagent_runner.log"),
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
                user_time=datetime.now(timezone.utc),
            ):
                chunks.append(c)

        # nostream with complete_message and DONE
        assert any("nostream:" in c for c in chunks)
        assert any("DONE" in c for c in chunks)


# ---------------------------------------------------------------------------
# subagent_helpers.py — build_subagent_system_prompt
# ---------------------------------------------------------------------------


from app.agents.core.subagents.subagent_helpers import (  # noqa: E402
    build_subagent_system_prompt,
    create_agent_context_message,
    create_subagent_system_message,
)


@pytest.mark.unit
class TestBuildSubagentSystemPrompt:
    @pytest.mark.asyncio
    async def test_returns_base_prompt_with_metadata(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"Username": "testuser"},
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await build_subagent_system_prompt("github", user_id="u1")

        assert "You are the GitHub agent." in result
        assert "USER CONTEXT FOR GITHUB" in result
        assert "testuser" in result

    @pytest.mark.asyncio
    async def test_no_metadata_when_no_user_id(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
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
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
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
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB down"),
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await build_subagent_system_prompt("github", user_id="u1")

        # Should not raise, returns prompt without metadata
        assert "You are the GitHub agent." in result

    @pytest.mark.asyncio
    async def test_empty_metadata_no_context_injected(self):
        integration = _make_integration("github")

        with (
            patch(
                "app.agents.core.subagents.subagent_helpers.get_integration_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.subagent_helpers.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.agents.core.subagents.subagent_helpers.log"),
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
    async def test_includes_utc_time(self):
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
        assert "Current UTC Time:" in result.content

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
        assert "User Local Time:" in result.content

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
                "app.agents.core.subagents.subagent_helpers.memory_service.search_memories",
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
            patch("app.agents.core.subagents.subagent_helpers.log"),
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
            patch("app.agents.core.subagents.subagent_helpers.log"),
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
            patch("app.agents.core.subagents.subagent_helpers.log"),
        ):
            result = await create_agent_context_message(
                configurable={"user_time": "not-a-valid-time"},
            )

        # Should not raise
        assert isinstance(result, SystemMessage)
        assert "Current UTC Time:" in result.content

    @pytest.mark.asyncio
    async def test_memory_message_flag(self):
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

        # SystemMessage should have memory_message=True
        assert getattr(result, "memory_message", False) is True
