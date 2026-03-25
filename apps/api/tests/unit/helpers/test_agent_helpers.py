"""Comprehensive tests for app/helpers/agent_helpers.py."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.helpers.agent_helpers import (
    _extract_timezone_offset,
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    get_custom_integration_metadata,
    get_handoff_metadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = "507f1f77bcf86cd799439011"
CONV_ID = "conv-001"

FAKE_USER = {
    "user_id": USER_ID,
    "email": "test@example.com",
    "name": "Test User",
}


def _make_user_time(offset_hours: int = 0) -> datetime:
    tz = timezone(timedelta(hours=offset_hours))
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=tz)


# ---------------------------------------------------------------------------
# _extract_timezone_offset
# ---------------------------------------------------------------------------


class TestExtractTimezoneOffset:
    def test_utc(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert _extract_timezone_offset(dt) == "+00:00"

    def test_positive_offset(self):
        tz = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2025, 1, 1, tzinfo=tz)
        assert _extract_timezone_offset(dt) == "+05:30"

    def test_negative_offset(self):
        tz = timezone(timedelta(hours=-8))
        dt = datetime(2025, 1, 1, tzinfo=tz)
        assert _extract_timezone_offset(dt) == "-08:00"

    def test_naive_datetime_returns_utc(self):
        dt = datetime(2025, 1, 1)
        assert _extract_timezone_offset(dt) == "+00:00"

    def test_none_utcoffset_returns_utc(self):
        """Datetime with tzinfo that returns None for utcoffset."""
        from datetime import tzinfo as _tzinfo

        class _NoneOffsetTZ(_tzinfo):
            def utcoffset(self, dt):
                return None

            def tzname(self, dt):
                return "NONE"

            def dst(self, dt):
                return None

        dt = datetime(2025, 1, 1, tzinfo=_NoneOffsetTZ())
        assert _extract_timezone_offset(dt) == "+00:00"

    def test_zero_negative_offset(self):
        tz = timezone(timedelta(hours=0))
        dt = datetime(2025, 1, 1, tzinfo=tz)
        assert _extract_timezone_offset(dt) == "+00:00"

    def test_large_positive_offset(self):
        tz = timezone(timedelta(hours=12, minutes=45))
        dt = datetime(2025, 1, 1, tzinfo=tz)
        assert _extract_timezone_offset(dt) == "+12:45"


# ---------------------------------------------------------------------------
# get_custom_integration_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCustomIntegrationMetadata:
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_no_category_returns_empty(self, mock_get_registry):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = None
        mock_get_registry.return_value = mock_registry

        result = await get_custom_integration_metadata("some_tool", USER_ID)
        assert result == {}

    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_non_mcp_category_returns_empty(self, mock_get_registry):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "gmail"
        mock_get_registry.return_value = mock_registry

        result = await get_custom_integration_metadata("gmail_send", USER_ID)
        assert result == {}

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_mcp_category_cache_hit(
        self, mock_get_registry, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "mcp_custom_reposearch_abc123"
        mock_get_registry.return_value = mock_registry
        mock_get_cache.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "custom_reposearch_abc123",
        }

        result = await get_custom_integration_metadata("repo_search", USER_ID)
        assert result["icon_url"] == "https://icon.png"

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_mcp_category_cache_miss_found_in_db(
        self, mock_get_registry, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "mcp_custom_tool"
        mock_get_registry.return_value = mock_registry
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(
            return_value={"name": "Custom Tool", "icon_url": "https://img.png"}
        )

        result = await get_custom_integration_metadata("my_tool", USER_ID)
        assert result["integration_name"] == "Custom Tool"
        assert result["icon_url"] == "https://img.png"
        mock_set_cache.assert_called_once()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_mcp_category_not_found_in_db(
        self, mock_get_registry, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "mcp_unknown"
        mock_get_registry.return_value = mock_registry
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(return_value=None)

        result = await get_custom_integration_metadata("unknown_tool", USER_ID)
        assert result == {}
        # Negative result cached
        mock_set_cache.assert_called_once()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_mcp_category_db_error_returns_empty(
        self, mock_get_registry, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "mcp_broken"
        mock_get_registry.return_value = mock_registry
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(side_effect=Exception("DB down"))

        result = await get_custom_integration_metadata("broken_tool", USER_ID)
        assert result == {}

    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_tool_registry", new_callable=AsyncMock)
    async def test_mcp_category_with_uuid_suffix_stripped(
        self, mock_get_registry, mock_get_cache
    ):
        """UUID-like suffix (>= 32 chars with dashes) should be stripped from integration ID."""
        mock_registry = MagicMock()
        # category: mcp_{integration_id}_{uuid_user_id}
        uuid_suffix = "550e8400-e29b-41d4-a716-446655440000"
        mock_registry.get_category_of_tool.return_value = (
            f"mcp_myintegration_{uuid_suffix}"
        )
        mock_get_registry.return_value = mock_registry
        mock_get_cache.return_value = {"integration_id": "myintegration"}

        result = await get_custom_integration_metadata("tool_x", USER_ID)
        assert result["integration_id"] == "myintegration"


# ---------------------------------------------------------------------------
# get_handoff_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetHandoffMetadata:
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS", [])
    async def test_cache_hit_returns_cached(self, mock_get_cache):
        mock_get_cache.return_value = {"integration_id": "github", "icon_url": None}

        result = await get_handoff_metadata("github")
        assert result["integration_id"] == "github"

    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS", [])
    async def test_cache_hit_empty_returns_empty(self, mock_get_cache):
        """Cached empty dict means negative cache hit."""
        mock_get_cache.return_value = {}

        result = await get_handoff_metadata("nonexistent")
        assert result == {}

    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS")
    async def test_platform_integration_match_by_id(self, mock_integrations):
        integ = MagicMock()
        integ.id = "github"
        integ.short_name = "gh"
        integ.name = "GitHub"
        integ.subagent_config = MagicMock()
        integ.subagent_config.has_subagent = True
        mock_integrations.__iter__ = MagicMock(return_value=iter([integ]))

        result = await get_handoff_metadata("github")
        assert result["integration_id"] == "github"
        assert result["integration_name"] == "GitHub"
        assert result["icon_url"] is None

    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS")
    async def test_platform_integration_match_by_short_name(self, mock_integrations):
        integ = MagicMock()
        integ.id = "github"
        integ.short_name = "gh"
        integ.name = "GitHub"
        integ.subagent_config = MagicMock()
        integ.subagent_config.has_subagent = True
        mock_integrations.__iter__ = MagicMock(return_value=iter([integ]))

        result = await get_handoff_metadata("gh")
        assert result["integration_name"] == "GitHub"

    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS")
    async def test_platform_integration_no_subagent(self, mock_integrations):
        """Platform integration without subagent config falls through."""
        integ = MagicMock()
        integ.id = "slack"
        integ.short_name = None
        integ.name = "Slack"
        integ.subagent_config = MagicMock()
        integ.subagent_config.has_subagent = False
        mock_integrations.__iter__ = MagicMock(return_value=iter([integ]))

        with (
            patch(
                "app.helpers.agent_helpers.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock),
            patch("app.helpers.agent_helpers.integrations_collection") as mock_col,
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            result = await get_handoff_metadata("slack")
        assert result == {}

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS", [])
    async def test_custom_integration_found_in_db(
        self, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(
            return_value={
                "name": "MyMCP",
                "icon_url": "https://icon.png",
                "integration_id": "custom_mymcp",
            }
        )

        result = await get_handoff_metadata("custom_mymcp")
        assert result["integration_name"] == "MyMCP"
        mock_set_cache.assert_called_once()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS", [])
    async def test_custom_integration_db_error_returns_empty(
        self, mock_col, mock_get_cache, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(side_effect=Exception("DB failure"))

        result = await get_handoff_metadata("broken")
        assert result == {}

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.OAUTH_INTEGRATIONS", [])
    async def test_handoff_with_subagent_prefix(
        self, mock_col, mock_get_cache, mock_set_cache
    ):
        """Subagent IDs may have 'subagent:' prefix."""
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(
            return_value={
                "name": "Custom",
                "icon_url": None,
                "integration_id": "custom_abc",
            }
        )

        result = await get_handoff_metadata("subagent:custom_abc")
        assert result["integration_name"] == "Custom"


# ---------------------------------------------------------------------------
# build_agent_config
# ---------------------------------------------------------------------------


class TestBuildAgentConfig:
    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_basic_config(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None  # no posthog

        user_time = _make_user_time(5)
        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=user_time,
            agent_name="comms_agent",
        )

        assert config["configurable"]["thread_id"] == CONV_ID
        assert config["configurable"]["user_id"] == USER_ID
        assert config["configurable"]["user_timezone"] == "+05:00"
        assert config["recursion_limit"] == 75

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_custom_thread_id(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="comms_agent",
            thread_id="custom-thread",
        )
        assert config["configurable"]["thread_id"] == "custom-thread"

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_user_model_config(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None

        model_cfg = MagicMock()
        model_cfg.provider_model_name = "gpt-4"
        model_cfg.inference_provider.value = "openai"
        model_cfg.max_tokens = 8000

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="executor",
            user_model_config=model_cfg,
        )
        assert config["configurable"]["model_name"] == "gpt-4"
        assert config["configurable"]["provider"] == "openai"
        assert config["configurable"]["max_tokens"] == 8000

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_base_configurable_inheritance(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None

        base = {
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3",
            "selected_tool": "web_search",
            "vfs_session_id": "vfs-sess-1",
        }

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="executor",
            base_configurable=base,
        )
        assert config["configurable"]["provider"] == "anthropic"
        assert config["configurable"]["selected_tool"] == "web_search"
        assert config["configurable"]["vfs_session_id"] == "vfs-sess-1"

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_opik_tracer_added_in_production(self, mock_settings, mock_providers):
        mock_settings.ENV = "production"
        mock_settings.OPIK_API_KEY = "key"  # pragma: allowlist secret
        mock_settings.OPIK_WORKSPACE = "ws"
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="comms_agent",
        )
        # Should have at least the OpikTracer callback
        assert len(config["callbacks"]) >= 1

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_posthog_callback_added(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = MagicMock()  # posthog client present

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="comms_agent",
        )
        assert len(config["callbacks"]) >= 1

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_usage_metadata_callback(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None

        usage_cb = MagicMock()
        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="comms_agent",
            usage_metadata_callback=usage_cb,
        )
        assert usage_cb in config["callbacks"]

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.settings")
    def test_selected_tool_and_category(self, mock_settings, mock_providers):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            user_time=_make_user_time(),
            agent_name="comms_agent",
            selected_tool="search",
            tool_category="web",
        )
        assert config["configurable"]["selected_tool"] == "search"
        assert config["configurable"]["tool_category"] == "web"


# ---------------------------------------------------------------------------
# build_initial_state
# ---------------------------------------------------------------------------


class TestBuildInitialState:
    def test_basic_state(self):
        request = MagicMock()
        request.message = "Hello"
        request.selectedTool = None
        request.selectedWorkflow = None
        request.selectedCalendarEvent = None

        state = build_initial_state(request, USER_ID, CONV_ID, [])

        assert state["query"] == "Hello"
        assert state["mem0_user_id"] == USER_ID
        assert state["conversation_id"] == CONV_ID
        assert state["messages"] == []
        assert "trigger_context" not in state

    def test_with_trigger_context(self):
        request = MagicMock()
        request.message = "Trigger"
        request.selectedTool = "tool_x"
        request.selectedWorkflow = None
        request.selectedCalendarEvent = None

        ctx = {"trigger": "reminder", "data": {}}
        state = build_initial_state(request, USER_ID, CONV_ID, [], trigger_context=ctx)

        assert state["trigger_context"] == ctx
        assert state["selected_tool"] == "tool_x"

    def test_with_all_selections(self):
        request = MagicMock()
        request.message = "Do stuff"
        request.selectedTool = "toolA"
        request.selectedWorkflow = "workflow1"
        request.selectedCalendarEvent = "event123"

        state = build_initial_state(request, USER_ID, CONV_ID, ["msg1"])

        assert state["selected_tool"] == "toolA"
        assert state["selected_workflow"] == "workflow1"
        assert state["selected_calendar_event"] == "event123"
        assert state["messages"] == ["msg1"]


# ---------------------------------------------------------------------------
# execute_graph_silent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteGraphSilent:
    async def test_accumulates_message_content(self):
        """Verifies AIMessageChunk content from comms_agent is accumulated."""
        chunk = MagicMock()
        chunk.text = "Hello "
        chunk.__class__.__name__ = "AIMessageChunk"
        # Make isinstance check work
        from langchain_core.messages import AIMessageChunk as AIMC

        chunk2 = MagicMock(spec=AIMC)
        chunk2.text = "world"
        chunk2.content = "world"

        chunk1 = MagicMock(spec=AIMC)
        chunk1.text = "Hello "
        chunk1.content = "Hello "

        events = [
            ((), "messages", (chunk1, {"agent_name": "comms_agent"})),
            ((), "messages", (chunk2, {"agent_name": "comms_agent"})),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, tool_data = await execute_graph_silent(
            graph,
            {"query": "test"},
            {"configurable": {"user_id": USER_ID}},
        )

        assert msg == "Hello world"

    async def test_skips_silent_chunks(self):
        from langchain_core.messages import AIMessageChunk as AIMC

        chunk = MagicMock(spec=AIMC)
        chunk.text = "should be skipped"
        chunk.content = "should be skipped"

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent", "silent": True})),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )
        assert msg == ""

    async def test_skips_non_comms_agent_chunks(self):
        from langchain_core.messages import AIMessageChunk as AIMC

        chunk = MagicMock(spec=AIMC)
        chunk.text = "executor text"
        chunk.content = "executor text"

        events = [
            ((), "messages", (chunk, {"agent_name": "executor_agent"})),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )
        assert msg == ""

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools")
    async def test_custom_events_merged(self, mock_process):
        mock_process.return_value = {
            "tool_data": [{"tool_name": "custom_tool"}],
            "follow_up_actions": ["action1"],
        }

        events = [
            ((), "custom", {"some": "data"}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )
        assert len(tool_data["tool_data"]) == 1
        assert tool_data["follow_up_actions"] == ["action1"]

    async def test_todo_progress_accumulated(self):
        events = [
            ((), "custom", {"todo_progress": {"source": "executor", "count": 3}}),
            ((), "custom", {"todo_progress": {"source": "executor", "count": 5}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.process_custom_event_for_tools",
            return_value=None,
        ):
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        # Should have one todo_progress entry
        todo_entries = [
            e for e in tool_data["tool_data"] if e["tool_name"] == "todo_progress"
        ]
        assert len(todo_entries) == 1
        # Last snapshot wins
        assert todo_entries[0]["data"]["executor"]["count"] == 5

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_updates_handoff_tool_calls(self, mock_handoff, mock_format):
        mock_handoff.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "github",
        }
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        msg = MagicMock()
        msg.tool_calls = [
            {"id": "tc1", "name": "handoff", "args": {"subagent_id": "github"}}
        ]

        events = [
            ((), "updates", {"node1": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )

        mock_handoff.assert_called_once_with("github")
        assert len(tool_data["tool_data"]) == 1

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch(
        "app.helpers.agent_helpers.get_custom_integration_metadata",
        new_callable=AsyncMock,
    )
    async def test_updates_custom_tool_calls(self, mock_custom_meta, mock_format):
        mock_custom_meta.return_value = {"icon_url": None, "integration_id": "mcp_x"}
        mock_format.return_value = {"tool_name": "custom_tool", "data": {}}

        msg = MagicMock()
        msg.tool_calls = [{"id": "tc2", "name": "custom_tool", "args": {}}]

        events = [
            ((), "updates", {"node1": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )

        mock_custom_meta.assert_called_once()

    async def test_updates_skips_plan_tasks(self):
        """plan_tasks and update_tasks tool calls should be skipped."""
        msg = MagicMock()
        msg.tool_calls = [
            {"id": "tc_plan", "name": "plan_tasks", "args": {}},
            {"id": "tc_update", "name": "update_tasks", "args": {}},
        ]

        events = [
            ((), "updates", {"node1": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )

        assert len(tool_data["tool_data"]) == 0

    async def test_updates_deduplicates_tool_calls(self):
        """Same tool call ID should not be emitted twice."""
        msg = MagicMock()
        msg.tool_calls = [{"id": "tc_dup", "name": "some_tool", "args": {}}]

        events = [
            ((), "updates", {"node1": {"messages": [msg]}}),
            ((), "updates", {"node2": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with (
            patch(
                "app.helpers.agent_helpers.get_custom_integration_metadata",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.helpers.agent_helpers.format_tool_call_entry",
                new_callable=AsyncMock,
                return_value={"tool_name": "t"},
            ),
        ):
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        assert len(tool_data["tool_data"]) == 1


# ---------------------------------------------------------------------------
# execute_graph_streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteGraphStreaming:
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_yields_done_at_end(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        events = []
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for chunk in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(chunk)

        assert any("[DONE]" in r for r in results)
        assert any("nostream" in r for r in results)

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_cancellation(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=True)

        from langchain_core.messages import AIMessageChunk as AIMC

        chunk = MagicMock(spec=AIMC)
        chunk.text = "text"
        chunk.content = "text"

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for chunk_str in execute_graph_streaming(
            graph,
            {},
            {"configurable": {"stream_id": "s1"}},
        ):
            results.append(chunk_str)

        assert any("cancelled" in r for r in results)

    @patch("app.helpers.agent_helpers.stream_manager")
    @patch("app.helpers.agent_helpers.format_sse_response")
    async def test_streams_ai_content(self, mock_format_sse, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format_sse.return_value = "data: Hello\n\n"

        from langchain_core.messages import AIMessageChunk as AIMC

        chunk = MagicMock(spec=AIMC)
        chunk.text = "Hello"
        chunk.content = "Hello"

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert any("Hello" in r for r in results)

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_handles_2_tuple_events(self, mock_sm):
        """When subgraphs=True but event is 2-tuple, handle gracefully."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        events = [
            ("messages", (MagicMock(spec=[]), {"agent_name": "x"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        # Should complete without error
        assert any("[DONE]" in r for r in results)

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_handles_unexpected_tuple_length(self, mock_sm):
        """Events with unexpected tuple length should be skipped."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        events = [
            ("single_element",),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert any("[DONE]" in r for r in results)


# ---------------------------------------------------------------------------
# Async iterator helper
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item
