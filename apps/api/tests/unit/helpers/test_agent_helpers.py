"""Comprehensive tests for app/helpers/agent_helpers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.helpers.agent_helpers import (
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    get_handoff_metadata,
)
from app.models.integration_models import Integration
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent


def _integration(integration_id: str, name: str, icon_url: str | None = None) -> Integration:
    return Integration(
        integration_id=integration_id,
        name=name,
        description="",
        category="custom",
        managed_by="mcp",
        icon_url=icon_url,
    )


def _make_subagent(
    subagent_id: str = "github",
    short_name: str | None = "gh",
    name: str = "GitHub",
) -> Subagent:
    """Build a real Subagent for handoff metadata tests."""
    config = SubAgentConfig(
        has_subagent=True,
        agent_name=f"{subagent_id}_agent",
        tool_space=f"{subagent_id}_space",
        handoff_tool_name=f"call_{subagent_id}",
        domain=subagent_id,
        capabilities=f"{subagent_id} stuff",
        use_cases=f"{subagent_id} use",
        system_prompt=f"You are the {subagent_id} agent.",
    )
    return Subagent(
        id=subagent_id,
        name=name,
        provider=subagent_id,
        managed_by="composio",
        config=config,
        short_name=short_name,
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


# ---------------------------------------------------------------------------
# get_handoff_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetHandoffMetadata:
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_cache_hit_returns_cached(self, mock_lookup, mock_get_cache):
        """Cache check happens AFTER the registry lookup; lookup must miss
        first so the code path falls through to the Redis cache."""
        mock_get_cache.return_value = {"integration_id": "github", "icon_url": None}

        result = await get_handoff_metadata("github")
        assert result["integration_id"] == "github"

    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_cache_hit_empty_returns_empty(self, mock_lookup, mock_get_cache):
        """Cached empty dict means negative cache hit."""
        mock_get_cache.return_value = {}

        result = await get_handoff_metadata("nonexistent")
        assert result == {}

    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_platform_integration_match_by_id(self, mock_lookup):
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("github")
        assert result["integration_id"] == "github"
        assert result["integration_name"] == "GitHub"
        assert result["icon_url"] is None

    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_platform_integration_match_by_short_name(self, mock_lookup):
        # The registry's get_subagent_by_id resolves short_name itself —
        # the mock just returns the same Subagent regardless of input.
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("gh")
        assert result["integration_name"] == "GitHub"

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_custom_integration_found_in_db(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(
            return_value=_integration("custom_mymcp", "MyMCP", "https://icon.png")
        )

        result = await get_handoff_metadata("custom_mymcp")
        assert result["integration_name"] == "MyMCP"
        mock_set_cache.assert_called_once()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_custom_integration_db_error_returns_empty(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(side_effect=Exception("DB failure"))

        result = await get_handoff_metadata("broken")
        assert result == {}

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_handoff_with_subagent_prefix(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache
    ):
        """Subagent IDs may have 'subagent:' prefix — parse_subagent_id strips it
        before the registry lookup, so the mock should see 'custom_abc'."""
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(
            return_value=_integration("custom_abc", "Custom")
        )

        result = await get_handoff_metadata("subagent:custom_abc")
        assert result["integration_name"] == "Custom"
        # parse_subagent_id strips "subagent:" → registry sees "custom_abc"
        mock_lookup.assert_called_once_with("custom_abc")


# ---------------------------------------------------------------------------
# build_agent_config
# ---------------------------------------------------------------------------


class TestBuildAgentConfig:
    @patch("app.helpers.agent_helpers.providers")
    def test_basic_config(self, mock_providers):
        mock_providers.get.return_value = None  # no posthog

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
        )

        from app.constants.llm import AGENT_RECURSION_LIMIT

        assert config["configurable"]["thread_id"] == CONV_ID
        assert config["configurable"]["user_id"] == USER_ID
        # No stored home zone and no parent zone -> UTC.
        assert config["configurable"]["user_timezone"] == "UTC"
        assert config["recursion_limit"] == AGENT_RECURSION_LIMIT

    @patch("app.helpers.agent_helpers.providers")
    def test_uses_home_profile_timezone(self, mock_providers):
        """The agent operates in the user's stored home zone (IANA, DST-aware)."""
        mock_providers.get.return_value = None

        home_user = {**FAKE_USER, "timezone": "Asia/Kolkata"}
        config = build_agent_config(
            conversation_id=CONV_ID,
            user=home_user,
            agent_name="comms_agent",
        )
        assert config["configurable"]["user_timezone"] == "Asia/Kolkata"

    @patch("app.helpers.agent_helpers.providers")
    def test_inherits_home_timezone_from_base_configurable(self, mock_providers):
        """A child agent reconstructs a bare user dict, so it inherits the home
        zone from the parent's configurable (user_timezone)."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,  # no timezone on the user dict
            agent_name="executor",
            base_configurable={"user_timezone": "Asia/Kolkata"},
        )
        assert config["configurable"]["user_timezone"] == "Asia/Kolkata"

    @patch("app.helpers.agent_helpers.providers")
    def test_custom_thread_id(self, mock_providers):
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            thread_id="custom-thread",
        )
        assert config["configurable"]["thread_id"] == "custom-thread"

    @patch("app.helpers.agent_helpers.providers")
    def test_user_model_config(self, mock_providers):
        mock_providers.get.return_value = None

        model_cfg = MagicMock()
        model_cfg.provider_model_name = "gpt-4"
        model_cfg.inference_provider.value = "openai"
        model_cfg.max_tokens = 8000

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            user_model_config=model_cfg,
        )
        assert config["configurable"]["model_name"] == "gpt-4"
        assert config["configurable"]["provider"] == "openai"
        assert config["configurable"]["max_tokens"] == 8000

    @patch("app.helpers.agent_helpers.providers")
    def test_base_configurable_inheritance(self, mock_providers):
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
            agent_name="executor",
            base_configurable=base,
        )
        assert config["configurable"]["provider"] == "anthropic"
        assert config["configurable"]["selected_tool"] == "web_search"
        assert config["configurable"]["vfs_session_id"] == "vfs-sess-1"

    @patch("app.helpers.agent_helpers.providers")
    def test_every_parent_fallback_key_fills_only_its_own_blank(self, mock_providers):
        """Each fallback key inherits from the SAME key on the parent, and no other.

        The seven fallback keys are written out one per line in
        ``_inherit_from_parent_configurable``. Two of them crossed (a line
        reading ``subagent_id`` into ``tool_category``) type-checks fine — both
        are declared ``str | None`` on ``AgentConfigurable`` — so only distinct
        values per key can catch it. Giving every key a unique value is what
        makes a swap visible.
        """
        mock_providers.get.return_value = None
        base = {
            "selected_tool": "parent-tool",
            "tool_category": "parent-category",
            "subagent_id": "parent-subagent",
            "vfs_session_id": "parent-vfs",
            "active_todo_id": "parent-todo",
            "execution_mode": "background",
            "conversation_source": "telegram",
        }

        inherited = build_agent_config(
            conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor", base_configurable=base
        )["configurable"]
        assert {key: inherited[key] for key in base} == base

    @patch("app.helpers.agent_helpers.providers")
    def test_child_value_wins_over_parent_for_fallback_keys(self, mock_providers):
        """The parent only fills a blank — an explicit child value is never clobbered."""
        mock_providers.get.return_value = None

        configurable = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={
                "selected_tool": "parent-tool",
                "tool_category": "parent-category",
                "subagent_id": "parent-subagent",
                "vfs_session_id": "parent-vfs",
                "active_todo_id": "parent-todo",
                "execution_mode": "background",
                "conversation_source": "telegram",
            },
            selected_tool="child-tool",
            tool_category="child-category",
            subagent_id="child-subagent",
            vfs_session_id="child-vfs",
            active_todo_id="child-todo",
            execution_mode="interactive",
            source="web",
        )["configurable"]

        assert configurable["selected_tool"] == "child-tool"
        assert configurable["tool_category"] == "child-category"
        assert configurable["subagent_id"] == "child-subagent"
        assert configurable["vfs_session_id"] == "child-vfs"
        assert configurable["active_todo_id"] == "child-todo"
        assert configurable["execution_mode"] == "interactive"
        assert configurable["conversation_source"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    def test_parent_overrides_child_for_conversation_id_and_user_messages(self, mock_providers):
        """The TRUE conversation id and the user's verbatim turns are established
        once by comms; a child passing its own wrapped thread id or an
        agent-authored paraphrase must not overwrite them (the HIL intent judge
        grounds gated calls against the user's own words)."""
        mock_providers.get.return_value = None

        configurable = build_agent_config(
            conversation_id="github_executor_conv-1",
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={
                "conversation_id": "conv-1",
                "user_messages": ["delete the repo"],
            },
            user_messages=["the agent's paraphrase"],
        )["configurable"]

        assert configurable["conversation_id"] == "conv-1"
        assert configurable["user_messages"] == ["delete the repo"]
        # thread_id still tracks the wrapped graph thread, unlike conversation_id.
        assert configurable["thread_id"] == "github_executor_conv-1"

    @patch("app.helpers.agent_helpers.providers")
    def test_a_handoff_subagent_inherits_preferences_established_by_comms(
        self, mock_providers
    ) -> None:
        """``user_preferences`` / ``writing_style`` follow the exact same rule as
        ``user_messages`` above: established once wherever the root call site has
        the full user document (comms), a child agent (executor, a handoff
        subagent) never has its own copy to prefer, so the parent's value wins."""
        mock_providers.get.return_value = None

        configurable = build_agent_config(
            conversation_id="conv-1",
            user=FAKE_USER,
            agent_name="gmail_agent",
            base_configurable={
                "conversation_id": "conv-1",
                "user_preferences": {"profession": "engineer"},
                "writing_style": {"summary": "terse"},
            },
        )["configurable"]

        assert configurable["user_preferences"] == {"profession": "engineer"}
        assert configurable["writing_style"] == {"summary": "terse"}

    @patch("app.helpers.agent_helpers.providers")
    def test_no_parent_and_no_explicit_value_leaves_preferences_absent(
        self, mock_providers
    ) -> None:
        """A root call site with no onboarding data (e.g. a dev user who hasn't
        onboarded) must not fabricate a value — the context section reads a
        missing key as "render nothing", never as a stale default."""
        mock_providers.get.return_value = None

        configurable = build_agent_config(
            conversation_id="conv-1", user=FAKE_USER, agent_name="executor_agent"
        )["configurable"]

        assert configurable["user_preferences"] is None
        assert configurable["writing_style"] is None

    @patch("app.helpers.agent_helpers.providers")
    def test_stream_id_always_comes_from_the_parent(self, mock_providers):
        """Pass-through, not a fallback: a child never invents its own stream."""
        mock_providers.get.return_value = None

        with_parent = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={"stream_id": "stream-9"},
        )["configurable"]
        without_parent = build_agent_config(
            conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent"
        )["configurable"]

        assert with_parent["stream_id"] == "stream-9"
        assert without_parent["stream_id"] is None

    @patch("app.helpers.agent_helpers.providers")
    def test_posthog_callback_added(self, mock_providers):
        mock_providers.get.return_value = MagicMock()  # posthog client present

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
        )
        assert len(config["callbacks"]) >= 1

    @patch("app.helpers.agent_helpers.providers")
    def test_usage_metadata_callback(self, mock_providers):
        mock_providers.get.return_value = None

        usage_cb = MagicMock()
        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            usage_metadata_callback=usage_cb,
        )
        assert usage_cb in config["callbacks"]

    @patch("app.helpers.agent_helpers.providers")
    def test_selected_tool_and_category(self, mock_providers):
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            selected_tool="search",
            tool_category="web",
        )
        assert config["configurable"]["selected_tool"] == "search"
        assert config["configurable"]["tool_category"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    def test_bot_source_sets_bot_category_and_channel(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            source="whatsapp",
        )
        # raw channel preserved in configurable; generalized category derived
        assert config["configurable"]["conversation_source"] == "whatsapp"
        assert config["configurable"]["source_category"] == "bot"
        # both surfaced on trace metadata for observability
        assert config["metadata"]["source_category"] == "bot"
        assert config["metadata"]["source_channel"] == "whatsapp"

    @patch("app.helpers.agent_helpers.providers")
    def test_web_source_sets_ui_category(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            source="web",
        )
        assert config["configurable"]["source_category"] == "ui"
        assert config["metadata"]["source_category"] == "ui"
        assert config["metadata"]["source_channel"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    def test_missing_source_defaults_to_background(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
        )
        # no source -> BG category, channel labelled "background" in metadata
        assert config["configurable"]["conversation_source"] is None
        assert config["configurable"]["source_category"] == "bg"
        assert config["metadata"]["source_category"] == "bg"
        assert config["metadata"]["source_channel"] == "background"

    @patch("app.helpers.agent_helpers.providers")
    def test_source_inherited_from_base_configurable(self, mock_providers) -> None:
        """A child agent (e.g. executor) inherits the channel from its parent and
        recomputes the category — so background runs are still tagged Bot/UI."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={"conversation_source": "telegram"},
        )
        assert config["configurable"]["conversation_source"] == "telegram"
        assert config["configurable"]["source_category"] == "bot"
        assert config["metadata"]["source_channel"] == "telegram"


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
        assert state["memory_user_id"] == USER_ID
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
            {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}},
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

        # agent_name is comms_agent, so only the `silent` flag should suppress it.
        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}},
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

        # Non-comms agent: content must NOT be accumulated even though it exists.
        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"agent_name": "executor_agent", "configurable": {"user_id": USER_ID}},
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
        todo_entries = [e for e in tool_data["tool_data"] if e["tool_name"] == "todo_progress"]
        assert len(todo_entries) == 1
        # Last snapshot wins
        assert todo_entries[0]["data"]["executor"]["count"] == 5

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_updates_handoff_tool_calls(self, mock_handoff, mock_format):
        """handoff tool calls on the agent node resolve + forward handoff metadata."""
        mock_handoff.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "github",
        }
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        msg = MagicMock()
        msg.tool_calls = [{"id": "tc1", "name": "handoff", "args": {"subagent_id": "github"}}]

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )

        mock_handoff.assert_called_once_with("github")
        # The resolved handoff metadata must be forwarded into the formatted entry.
        assert mock_format.await_args.kwargs["integration_id"] == "github"
        assert tool_data["tool_data"] == [{"tool_name": "handoff", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_updates_regular_tool_calls_thread_user_id(self, mock_format):
        """Non-handoff tool calls are formatted with the originating user_id (so
        format_tool_call_entry can resolve MCP metadata) and appended."""
        mock_format.return_value = {"tool_name": "custom_tool", "data": {}}

        msg = MagicMock()
        msg.tool_calls = [{"id": "tc2", "name": "custom_tool", "args": {}}]

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )

        mock_format.assert_awaited_once()
        assert mock_format.await_args.kwargs["user_id"] == USER_ID
        assert tool_data["tool_data"] == [{"tool_name": "custom_tool", "data": {}}]

    async def test_updates_ignores_non_agent_nodes(self):
        """Tool calls from non-'agent' nodes (e.g. pre-model hooks replaying old
        history) must not be collected."""
        msg = MagicMock()
        msg.tool_calls = [{"id": "tc_hook", "name": "some_tool", "args": {}}]

        events = [
            ((), "updates", {"pre_model_hook": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "some_tool"},
        ) as mock_format:
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        mock_format.assert_not_awaited()
        assert tool_data["tool_data"] == []

    async def test_updates_skips_plan_tasks(self):
        """plan_tasks and update_tasks tool calls are filtered before formatting."""
        msg = MagicMock()
        msg.tool_calls = [
            {"id": "tc_plan", "name": "plan_tasks", "args": {}},
            {"id": "tc_update", "name": "update_tasks", "args": {}},
        ]

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "should_not_appear"},
        ) as mock_format:
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        mock_format.assert_not_awaited()
        assert len(tool_data["tool_data"]) == 0

    async def test_updates_deduplicates_tool_calls(self):
        """Same tool call ID across multiple agent updates is emitted once."""
        msg = MagicMock()
        msg.tool_calls = [{"id": "tc_dup", "name": "some_tool", "args": {}}]

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "updates", {"agent": {"messages": [msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "t"},
        ) as mock_format:
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        assert mock_format.await_count == 1  # the duplicate is not formatted again
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
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
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
