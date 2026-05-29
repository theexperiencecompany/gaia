"""Mutation-verified unit tests for app/helpers/agent_helpers.py.

UNIT: app/helpers/agent_helpers.py
COVERS: _extract_timezone_offset, _resolve_model_config, _inherit_from_parent_configurable,
        _build_agent_callbacks, build_agent_config, build_initial_state,
        get_handoff_metadata, execute_graph_silent, execute_graph_streaming.

----------------------------------------------------------------------------
_extract_timezone_offset(user_time) -> str
EXPECTED: render a datetime's UTC offset as "+HH:MM" / "-HH:MM"; "+00:00" for
          naive datetimes or tzinfo whose utcoffset() is None.
MECHANISM: tzinfo None -> "+00:00"; utcoffset() None -> "+00:00"; else format
           sign + zero-padded hours/minutes from total offset seconds.
MUST-CATCH:
  - naive datetime returns exactly "+00:00" (the early return)
  - utcoffset()==None returns "+00:00" (the second guard)
  - positive offset gets "+", negative gets "-" (sign branch on >= 0)
  - hours and minutes are zero-padded to 2 digits and split correctly (3600 / 60)
  - +00:00 offset uses "+" (boundary: total_seconds >= 0 inclusive)

_resolve_model_config(user_model_config) -> (model_name, provider, max_tokens)
EXPECTED: user-selected triple when a config is given, library defaults otherwise.
MUST-CATCH:
  - user config returns provider_model_name / inference_provider.value / max_tokens
    in that exact tuple order
  - None config returns (DEFAULT_MODEL_NAME, DEFAULT_LLM_PROVIDER, DEFAULT_MAX_TOKENS)

_inherit_from_parent_configurable(base, current) -> dict
EXPECTED: parent overrides model fields; child wins on fallback fields (parent only
          fills blanks); stream_id/pinned_* always taken from parent.
MUST-CATCH:
  - no base: stream_id/pinned_memories/pinned_skills forced to None; current preserved
  - parent provider/max_tokens/model_name override the child's
  - fallback field present in child is NOT overwritten by parent
  - fallback field blank in child IS filled from parent's mapped key (source->conversation_source)
  - pinned_memories/pinned_skills come from the __pinned_*__ keys

build_agent_config(...) -> dict
EXPECTED: assemble the LangGraph config (configurable + recursion_limit + metadata +
          callbacks + agent_name), threading user/model/timezone/inheritance through.
MUST-CATCH:
  - thread_id defaults to conversation_id, overridable
  - user_timezone derived from user_time via _extract_timezone_offset
  - execution_mode defaults to "interactive" when unset
  - recursion_limit == AGENT_RECURSION_LIMIT
  - langfuse trace id (explicit) lands in configurable AND metadata; metadata gets
    session_id + user_id; empty-list tags clear (is not None semantics)
  - base_configurable model fields override defaults

build_initial_state(request, user_id, conversation_id, history, trigger_context) -> dict
EXPECTED: starting state with query/messages/ids/selections; trigger_context binds
          active_todo_id + execution_mode when present.
MUST-CATCH:
  - selections copied from request fields verbatim
  - no trigger_context -> key absent, no todo/mode injected
  - active_todo_id resolves from "active_todo_id" first, "todo_id" fallback
  - execution_mode injected only when present in trigger_context

get_handoff_metadata(subagent_id) -> dict
EXPECTED: resolve {icon_url, integration_id, integration_name} for a handoff subagent
          from platform registry, else Redis cache, else MongoDB (cached).
MUST-CATCH:
  - platform hit returns subagent.id/name with icon_url None (no DB/cache touched)
  - id is lowercased + parsed before lookup ("subagent:" stripped)
  - Redis positive cache hit returned as-is; empty cache -> {}
  - Mongo hit maps name->integration_name and caches positive; not-found caches {} and returns {}
  - Mongo error swallowed -> {}

execute_graph_silent(graph, state, config) -> (complete_message, tool_data)
EXPECTED: drain astream; accumulate comms_agent text, dedup agent-node tool_calls
          (skipping plan/update tasks, resolving handoff metadata), merge custom
          tool_data, fold todo_progress snapshots into one entry.
MUST-CATCH:
  - only comms_agent AIMessage(Chunk) content accumulates; silent + non-comms skipped
  - only the "agent" node's updates produce tool_data
  - plan_tasks/update_tasks suppressed; duplicate tc id emitted once
  - handoff tool resolves metadata and forwards it to format_tool_call_entry
  - custom tool_data entries appended; non-tool_data keys merged
  - todo_progress accumulates by source, last wins, emitted as single entry

execute_graph_streaming(graph, state, config) -> AsyncGenerator[str]
EXPECTED: SSE generator; stream comms_agent text, emit tool_data on agent updates,
          tool_output on ToolMessage, forward custom events; honor cancellation;
          always end with nostream + [DONE].
MUST-CATCH:
  - cancellation yields cancelled frame + [DONE] and stops early
  - 2-tuple and malformed events handled without crashing
  - comms_agent chunk -> format_sse_response emitted + accumulated
  - ToolMessage -> tool_output frame with tool_call_id + truncated output; todo tools skipped
  - terminal frames carry the accumulated complete_message

EQUIVALENT MUTANTS (allowed survivors, justified): documented inline where they arise.
"""

from datetime import UTC, datetime, timedelta, timezone, tzinfo as _tzinfo
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessageChunk, ToolMessage
import pytest

from app.constants.cache import CUSTOM_INT_METADATA_TTL, HANDOFF_METADATA_CACHE_PREFIX
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
)
from app.helpers.agent_helpers import (
    _extract_timezone_offset,
    _inherit_from_parent_configurable,
    _resolve_model_config,
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    get_handoff_metadata,
)
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent

USER_ID = "507f1f77bcf86cd799439011"
CONV_ID = "conv-001"
FAKE_USER = {"user_id": USER_ID, "email": "test@example.com", "name": "Test User"}


def _make_subagent(
    subagent_id: str = "github", short_name: str | None = "gh", name: str = "GitHub"
) -> Subagent:
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


def _make_user_time(offset_hours: int = 0, minutes: int = 0) -> datetime:
    tz = timezone(timedelta(hours=offset_hours, minutes=minutes))
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=tz)


async def _async_iter(items):
    for item in items:
        yield item


def _chunk(text: str) -> AIMessageChunk:
    """A real AIMessageChunk so isinstance() and .text behave like production."""
    return AIMessageChunk(content=text)


# ---------------------------------------------------------------------------
# _extract_timezone_offset
# ---------------------------------------------------------------------------


class TestExtractTimezoneOffset:
    def test_utc_offset_zero_uses_plus(self):
        assert _extract_timezone_offset(datetime(2025, 1, 1, tzinfo=UTC)) == "+00:00"

    def test_positive_offset_formats_hours_and_minutes(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert _extract_timezone_offset(dt) == "+05:30"

    def test_negative_offset_uses_minus_sign(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=-8)))
        assert _extract_timezone_offset(dt) == "-08:00"

    def test_naive_datetime_returns_utc(self):
        assert _extract_timezone_offset(datetime(2025, 1, 1)) == "+00:00"

    def test_tzinfo_with_none_utcoffset_returns_utc(self):
        class _NoneOffsetTZ(_tzinfo):
            def utcoffset(self, dt):
                return None

            def tzname(self, dt):
                return "NONE"

            def dst(self, dt):
                return None

        dt = datetime(2025, 1, 1, tzinfo=_NoneOffsetTZ())
        assert _extract_timezone_offset(dt) == "+00:00"

    def test_large_offset_zero_pads_both_components(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=12, minutes=45)))
        # 12:45 stays two digits each — guards the 3600 / 60 division split.
        assert _extract_timezone_offset(dt) == "+12:45"

    def test_minutes_only_offset_zero_pads_hours(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone(timedelta(minutes=15)))
        # Distinguishes hours=00 from minutes=15 — kills hour/minute swap mutants.
        assert _extract_timezone_offset(dt) == "+00:15"


# ---------------------------------------------------------------------------
# _resolve_model_config
# ---------------------------------------------------------------------------


class TestResolveModelConfig:
    def test_user_config_returns_provider_triple_in_order(self):
        cfg = MagicMock()
        cfg.provider_model_name = "gpt-4"
        cfg.inference_provider.value = "openai"
        cfg.max_tokens = 8000

        assert _resolve_model_config(cfg) == ("gpt-4", "openai", 8000)

    def test_no_config_returns_library_defaults(self):
        assert _resolve_model_config(None) == (
            DEFAULT_MODEL_NAME,
            DEFAULT_LLM_PROVIDER,
            DEFAULT_MAX_TOKENS,
        )


# ---------------------------------------------------------------------------
# _inherit_from_parent_configurable
# ---------------------------------------------------------------------------


class TestInheritFromParentConfigurable:
    def _current(self, **over):
        base = {
            "provider_name": "gemini",
            "max_tokens": 1000,
            "model_name": "flash",
            "selected_tool": None,
            "tool_category": None,
            "subagent_id": None,
            "vfs_session_id": None,
            "active_todo_id": None,
            "execution_mode": None,
            "source": None,
        }
        base.update(over)
        return base

    def test_no_base_forces_pass_through_to_none_and_keeps_current(self):
        merged = _inherit_from_parent_configurable(None, self._current(selected_tool="web"))
        assert merged["stream_id"] is None
        assert merged["pinned_memories"] is None
        assert merged["pinned_skills"] is None
        assert merged["selected_tool"] == "web"
        assert merged["provider_name"] == "gemini"

    def test_parent_overrides_model_fields(self):
        base = {"provider": "anthropic", "max_tokens": 4000, "model_name": "claude-3"}
        merged = _inherit_from_parent_configurable(base, self._current())
        assert merged["provider_name"] == "anthropic"
        assert merged["max_tokens"] == 4000
        assert merged["model_name"] == "claude-3"

    def test_child_fallback_field_not_overwritten_by_parent(self):
        base = {"selected_tool": "parent_tool"}
        merged = _inherit_from_parent_configurable(base, self._current(selected_tool="child_tool"))
        assert merged["selected_tool"] == "child_tool"

    def test_blank_child_fallback_filled_from_parent_with_source_remap(self):
        base = {"conversation_source": "discord", "subagent_id": "sub-1"}
        merged = _inherit_from_parent_configurable(base, self._current())
        # `source` maps from parent key `conversation_source`, not `source`.
        assert merged["source"] == "discord"
        assert merged["subagent_id"] == "sub-1"

    def test_pinned_sections_taken_from_double_underscore_keys(self):
        base = {
            "stream_id": "stream-9",
            "__pinned_memories__": [{"m": 1}],
            "__pinned_skills__": [{"s": 2}],
        }
        merged = _inherit_from_parent_configurable(base, self._current())
        assert merged["stream_id"] == "stream-9"
        assert merged["pinned_memories"] == [{"m": 1}]
        assert merged["pinned_skills"] == [{"s": 2}]


# ---------------------------------------------------------------------------
# build_agent_config
# ---------------------------------------------------------------------------


@patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
@patch("app.helpers.agent_helpers.providers")
@patch("app.helpers.agent_helpers.settings")
class TestBuildAgentConfig:
    def _dev_settings(self, mock_settings):
        mock_settings.ENV = "development"
        mock_settings.OPIK_API_KEY = None
        mock_settings.OPIK_WORKSPACE = None

    def test_thread_id_defaults_to_conversation_id(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        config = build_agent_config(CONV_ID, FAKE_USER, _make_user_time(5), "comms_agent")
        assert config["configurable"]["thread_id"] == CONV_ID
        assert config["configurable"]["user_id"] == USER_ID
        assert config["configurable"]["email"] == "test@example.com"
        assert config["configurable"]["user_timezone"] == "+05:00"
        assert config["configurable"]["execution_mode"] == "interactive"
        assert config["recursion_limit"] == AGENT_RECURSION_LIMIT
        assert config["agent_name"] == "comms_agent"

    def test_explicit_thread_id_overrides_default(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        config = build_agent_config(
            CONV_ID, FAKE_USER, _make_user_time(), "comms_agent", thread_id="custom-thread"
        )
        assert config["configurable"]["thread_id"] == "custom-thread"

    def test_user_model_config_drives_model_fields(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        cfg = MagicMock()
        cfg.provider_model_name = "gpt-4"
        cfg.inference_provider.value = "openai"
        cfg.max_tokens = 8000

        config = build_agent_config(
            CONV_ID, FAKE_USER, _make_user_time(), "executor", user_model_config=cfg
        )
        assert config["configurable"]["model_name"] == "gpt-4"
        assert config["configurable"]["model"] == "gpt-4"
        assert config["configurable"]["provider"] == "openai"
        assert config["configurable"]["max_tokens"] == 8000

    def test_base_configurable_model_fields_override_defaults(
        self, mock_settings, mock_providers, _lf
    ):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        base = {
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3",
            "selected_tool": "web_search",
            "vfs_session_id": "vfs-sess-1",
        }
        config = build_agent_config(
            CONV_ID, FAKE_USER, _make_user_time(), "executor", base_configurable=base
        )
        assert config["configurable"]["provider"] == "anthropic"
        assert config["configurable"]["selected_tool"] == "web_search"
        assert config["configurable"]["vfs_session_id"] == "vfs-sess-1"

    def test_explicit_langfuse_trace_propagates_to_configurable_and_metadata(
        self, mock_settings, mock_providers, _lf
    ):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        config = build_agent_config(
            CONV_ID,
            FAKE_USER,
            _make_user_time(),
            "comms_agent",
            langfuse_trace_id="trace-123",
            langfuse_tags=["a", "b"],
        )
        assert config["configurable"]["langfuse_trace_id"] == "trace-123"
        assert config["configurable"]["langfuse_tags"] == ["a", "b"]
        meta = config["metadata"]
        assert meta["langfuse_trace_id"] == "trace-123"
        assert meta["langfuse_session_id"] == CONV_ID
        assert meta["langfuse_user_id"] == USER_ID
        assert meta["langfuse_tags"] == ["a", "b"]

    def test_no_langfuse_trace_keeps_metadata_minimal(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        config = build_agent_config(CONV_ID, FAKE_USER, _make_user_time(), "comms_agent")
        assert "langfuse_trace_id" not in config["configurable"]
        assert config["metadata"] == {"user_id": USER_ID}

    def test_usage_callback_appended_when_provided(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        usage_cb = MagicMock()
        config = build_agent_config(
            CONV_ID,
            FAKE_USER,
            _make_user_time(),
            "comms_agent",
            usage_metadata_callback=usage_cb,
        )
        assert usage_cb in config["callbacks"]

    def test_no_optional_callbacks_yields_empty_list(self, mock_settings, mock_providers, _lf):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = False

        config = build_agent_config(CONV_ID, FAKE_USER, _make_user_time(), "comms_agent")
        # dev env, opik unconfigured, no posthog, no langfuse, no usage cb.
        assert config["callbacks"] == []

    def test_posthog_callback_added_when_provider_available(
        self, mock_settings, mock_providers, _lf
    ):
        self._dev_settings(mock_settings)
        mock_providers.is_available.return_value = True
        mock_providers.get.return_value = MagicMock()

        with patch("app.helpers.agent_helpers.PostHogCallbackHandler") as mock_ph:
            sentinel = MagicMock()
            mock_ph.return_value = sentinel
            config = build_agent_config(CONV_ID, FAKE_USER, _make_user_time(), "comms_agent")
        assert sentinel in config["callbacks"]


# ---------------------------------------------------------------------------
# build_initial_state
# ---------------------------------------------------------------------------


class TestBuildInitialState:
    def _request(self, message="Hello", tool=None, workflow=None, event=None):
        req = MagicMock()
        req.message = message
        req.selectedTool = tool
        req.selectedWorkflow = workflow
        req.selectedCalendarEvent = event
        return req

    def test_basic_state_copies_query_history_and_ids(self):
        state = build_initial_state(self._request("Hello"), USER_ID, CONV_ID, ["m1"])
        assert state["query"] == "Hello"
        assert state["intent"] == "Hello"
        assert state["mem0_user_id"] == USER_ID
        assert state["conversation_id"] == CONV_ID
        assert state["messages"] == ["m1"]
        assert state["integration_usernames"] == {}
        assert "trigger_context" not in state

    def test_selections_copied_verbatim(self):
        req = self._request("Do stuff", tool="toolA", workflow="wf1", event="evt-9")
        state = build_initial_state(req, USER_ID, CONV_ID, [])
        assert state["selected_tool"] == "toolA"
        assert state["selected_workflow"] == "wf1"
        assert state["selected_calendar_event"] == "evt-9"

    def test_trigger_context_stored_and_active_todo_id_preferred(self):
        ctx = {
            "active_todo_id": "todo-primary",
            "todo_id": "todo-fallback",
            "execution_mode": "scheduled",
        }
        state = build_initial_state(self._request(), USER_ID, CONV_ID, [], trigger_context=ctx)
        assert state["trigger_context"] == ctx
        assert state["active_todo_id"] == "todo-primary"
        assert state["execution_mode"] == "scheduled"

    def test_trigger_context_falls_back_to_todo_id(self):
        ctx = {"todo_id": "todo-fallback"}
        state = build_initial_state(self._request(), USER_ID, CONV_ID, [], trigger_context=ctx)
        assert state["active_todo_id"] == "todo-fallback"
        assert "execution_mode" not in state

    def test_trigger_context_without_todo_or_mode_injects_nothing(self):
        ctx = {"trigger": "reminder"}
        state = build_initial_state(self._request(), USER_ID, CONV_ID, [], trigger_context=ctx)
        assert state["trigger_context"] == ctx
        assert "active_todo_id" not in state
        assert "execution_mode" not in state


# ---------------------------------------------------------------------------
# get_handoff_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetHandoffMetadata:
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_platform_hit_returns_subagent_identity_without_io(
        self, mock_lookup, mock_get_cache
    ):
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("GitHub")  # mixed case -> lowercased

        assert result == {
            "icon_url": None,
            "integration_id": "github",
            "integration_name": "GitHub",
        }
        mock_lookup.assert_called_once_with("github")
        mock_get_cache.assert_not_called()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_redis_positive_cache_hit_short_circuits(
        self, mock_lookup, mock_get_cache, mock_col, mock_set_cache
    ):
        cached = {"integration_id": "github", "icon_url": None, "integration_name": "GitHub"}
        mock_get_cache.return_value = cached
        mock_col.find_one = AsyncMock()

        result = await get_handoff_metadata("github")

        assert result == cached
        mock_get_cache.assert_awaited_once_with(f"{HANDOFF_METADATA_CACHE_PREFIX}:github")
        mock_col.find_one.assert_not_called()
        mock_set_cache.assert_not_called()

    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_redis_empty_cache_hit_returns_empty(self, mock_lookup, mock_get_cache):
        mock_get_cache.return_value = {}
        assert await get_handoff_metadata("nonexistent") == {}

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_mongo_hit_maps_name_and_caches_positive(
        self, mock_lookup, mock_get_cache, mock_col, mock_set_cache
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

        assert result == {
            "icon_url": "https://icon.png",
            "integration_id": "custom_mymcp",
            "integration_name": "MyMCP",
        }
        mock_set_cache.assert_awaited_once_with(
            f"{HANDOFF_METADATA_CACHE_PREFIX}:custom_mymcp",
            result,
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_mongo_miss_caches_negative_and_returns_empty(
        self, mock_lookup, mock_get_cache, mock_col, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(return_value=None)

        result = await get_handoff_metadata("unknown")

        assert result == {}
        mock_set_cache.assert_awaited_once_with(
            f"{HANDOFF_METADATA_CACHE_PREFIX}:unknown",
            {},
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_mongo_error_swallowed_returns_empty(
        self, mock_lookup, mock_get_cache, mock_col, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(side_effect=Exception("DB down"))

        result = await get_handoff_metadata("broken")

        assert result == {}
        # On error we must NOT poison the cache with a (wrong) negative entry.
        mock_set_cache.assert_not_called()

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integrations_collection")
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_subagent_prefix_stripped_before_lookup(
        self, mock_lookup, mock_get_cache, mock_col, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_col.find_one = AsyncMock(
            return_value={"name": "Custom", "icon_url": None, "integration_id": "custom_abc"}
        )

        await get_handoff_metadata("subagent:custom_abc")

        # parse_subagent_id strips "subagent:" then lowercased -> "custom_abc".
        mock_lookup.assert_called_once_with("custom_abc")
        mock_get_cache.assert_awaited_once_with(f"{HANDOFF_METADATA_CACHE_PREFIX}:custom_abc")


# ---------------------------------------------------------------------------
# execute_graph_silent
# ---------------------------------------------------------------------------


def _silent_graph(events):
    graph = AsyncMock()
    graph.astream = MagicMock(return_value=_async_iter(events))
    return graph


@pytest.mark.asyncio
class TestExecuteGraphSilent:
    async def test_accumulates_only_comms_agent_text(self):
        events = [
            ((), "messages", (_chunk("Hello "), {})),  # default agent_name -> skipped
            ((), "messages", (_chunk("world"), {})),
        ]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        msg, _ = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert msg == "Hello world"

    async def test_non_comms_agent_text_not_accumulated(self):
        events = [((), "messages", (_chunk("executor text"), {}))]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "executor_agent"}
        msg, _ = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert msg == ""

    async def test_silent_metadata_chunk_skipped(self):
        events = [((), "messages", (_chunk("nope"), {"silent": True}))]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        msg, _ = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert msg == ""

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_only_agent_node_updates_emit_tool_data(self, mock_format):
        mock_format.return_value = {"tool_name": "t"}
        msg_obj = MagicMock()
        msg_obj.tool_calls = [{"id": "tc1", "name": "some_tool", "args": {}}]
        events = [((), "updates", {"filter_messages_node": {"messages": [msg_obj]}})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert tool_data["tool_data"] == []
        mock_format.assert_not_called()

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_handoff_metadata_resolved_and_forwarded(self, mock_handoff, mock_format):
        mock_handoff.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "github",
            "integration_name": "GitHub",
        }
        mock_format.return_value = {"tool_name": "handoff", "data": {}}
        msg_obj = MagicMock()
        msg_obj.tool_calls = [{"id": "tc1", "name": "handoff", "args": {"subagent_id": "github"}}]
        events = [((), "updates", {"agent": {"messages": [msg_obj]}})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}

        _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)

        mock_handoff.assert_awaited_once_with("github")
        # metadata fields are forwarded into format_tool_call_entry, not dropped.
        _, kwargs = mock_format.call_args
        assert kwargs["icon_url"] == "https://icon.png"
        assert kwargs["integration_id"] == "github"
        assert kwargs["integration_name"] == "GitHub"
        assert kwargs["user_id"] == USER_ID
        assert len(tool_data["tool_data"]) == 1

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_plan_and_update_tasks_suppressed(self, mock_format):
        mock_format.return_value = {"tool_name": "t"}
        msg_obj = MagicMock()
        msg_obj.tool_calls = [
            {"id": "p", "name": "plan_tasks", "args": {}},
            {"id": "u", "name": "update_tasks", "args": {}},
        ]
        events = [((), "updates", {"agent": {"messages": [msg_obj]}})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert tool_data["tool_data"] == []
        mock_format.assert_not_called()

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_duplicate_tool_call_id_emitted_once(self, mock_format):
        mock_format.return_value = {"tool_name": "t"}
        msg_obj = MagicMock()
        msg_obj.tool_calls = [{"id": "dup", "name": "some_tool", "args": {}}]
        events = [
            ((), "updates", {"agent": {"messages": [msg_obj]}}),
            ((), "updates", {"agent": {"messages": [msg_obj]}}),
        ]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert len(tool_data["tool_data"]) == 1

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools")
    async def test_custom_tool_data_appended_and_other_keys_merged(self, mock_process):
        mock_process.return_value = {
            "tool_data": [{"tool_name": "custom_tool"}],
            "follow_up_actions": ["action1"],
        }
        events = [((), "custom", {"some": "data"})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)
        assert {"tool_name": "custom_tool"} in tool_data["tool_data"]
        assert tool_data["follow_up_actions"] == ["action1"]

    async def test_todo_progress_accumulates_last_wins_single_entry(self):
        events = [
            ((), "custom", {"todo_progress": {"source": "executor", "count": 3}}),
            ((), "custom", {"todo_progress": {"source": "executor", "count": 5}}),
        ]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        with patch("app.helpers.agent_helpers.process_custom_event_for_tools", return_value=None):
            _, tool_data = await execute_graph_silent(_silent_graph(events), {}, cfg)
        todo_entries = [e for e in tool_data["tool_data"] if e["tool_name"] == "todo_progress"]
        assert len(todo_entries) == 1
        assert todo_entries[0]["data"]["executor"]["count"] == 5


# ---------------------------------------------------------------------------
# execute_graph_streaming
# ---------------------------------------------------------------------------


def _streaming_graph(events):
    graph = AsyncMock()
    graph.astream = MagicMock(return_value=_async_iter(events))
    return graph


async def _drain(gen):
    return [chunk async for chunk in gen]


@pytest.mark.asyncio
@patch("app.helpers.agent_helpers.stream_manager")
class TestExecuteGraphStreaming:
    async def test_terminal_frames_emitted_at_end(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        results = await _drain(
            execute_graph_streaming(_streaming_graph([]), {}, {"configurable": {}})
        )
        # Final two frames: nostream payload then [DONE].
        assert results[-1] == "data: [DONE]\n\n"
        nostream = json.loads(results[-2].removeprefix("nostream: "))
        assert nostream == {"complete_message": ""}

    async def test_cancellation_emits_cancelled_frame_and_stops_early(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=True)
        events = [((), "messages", (_chunk("late text"), {}))]
        cfg = {"configurable": {"stream_id": "s1"}, "agent_name": "comms_agent"}

        with patch("app.helpers.agent_helpers.format_sse_response") as mock_fmt:
            results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))

        cancel_frame = next(r for r in results if r.startswith("nostream: "))
        payload = json.loads(cancel_frame.removeprefix("nostream: "))
        assert payload == {"complete_message": "", "cancelled": True}
        assert results[-1] == "data: [DONE]\n\n"
        # We bailed before processing the message chunk.
        mock_fmt.assert_not_called()

    async def test_comms_agent_text_streamed_and_accumulated(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        events = [
            ((), "messages", (_chunk("Hel"), {})),
            ((), "messages", (_chunk("lo"), {})),
        ]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        with patch(
            "app.helpers.agent_helpers.format_sse_response",
            side_effect=lambda c: f"R:{c}",
        ):
            results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert "R:Hel" in results
        assert "R:lo" in results
        nostream = json.loads(results[-2].removeprefix("nostream: "))
        assert nostream["complete_message"] == "Hello"

    async def test_non_comms_agent_text_not_streamed(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        events = [((), "messages", (_chunk("executor"), {}))]
        cfg = {"configurable": {}, "agent_name": "executor_agent"}
        with patch("app.helpers.agent_helpers.format_sse_response", side_effect=lambda c: f"R:{c}"):
            results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert not any(r.startswith("R:") for r in results)
        nostream = json.loads(results[-2].removeprefix("nostream: "))
        assert nostream["complete_message"] == ""

    async def test_tool_message_emits_tool_output_frame(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        tool_msg = ToolMessage(content="search results", tool_call_id="tc-77", name="web_search")
        events = [((), "messages", (tool_msg, {}))]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))

        output_frame = next(r for r in results if '"tool_output"' in r)
        payload = json.loads(output_frame.removeprefix("data: "))
        assert payload["tool_output"]["tool_call_id"] == "tc-77"
        assert payload["tool_output"]["output"] == "search results"

    async def test_tool_message_output_truncated_to_3000_chars(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        long_content = "x" * 5000
        tool_msg = ToolMessage(content=long_content, tool_call_id="tc-1", name="web_search")
        events = [((), "messages", (tool_msg, {}))]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        payload = json.loads(
            next(r for r in results if '"tool_output"' in r).removeprefix("data: ")
        )
        assert len(payload["tool_output"]["output"]) == 3000

    async def test_todo_tool_message_suppressed(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        tool_msg = ToolMessage(content="ignored", tool_call_id="tc-9", name="plan_tasks")
        events = [((), "messages", (tool_msg, {}))]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert not any('"tool_output"' in r for r in results)

    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_agent_update_emits_tool_data_frame(self, mock_format, mock_handoff, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "tool_calls_data", "data": {}}
        msg_obj = MagicMock()
        msg_obj.tool_calls = [{"id": "tc-1", "name": "web_search", "args": {}}]
        events = [((), "updates", {"agent": {"messages": [msg_obj]}})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))

        frame = next(r for r in results if '"tool_data"' in r)
        payload = json.loads(frame.removeprefix("data: "))
        assert payload["tool_data"]["tool_name"] == "tool_calls_data"
        mock_handoff.assert_not_called()

    async def test_non_agent_node_update_emits_no_tool_data(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        msg_obj = MagicMock()
        msg_obj.tool_calls = [{"id": "tc-1", "name": "web_search", "args": {}}]
        events = [((), "updates", {"filter_messages_node": {"messages": [msg_obj]}})]
        cfg = {"configurable": {"user_id": USER_ID}, "agent_name": "comms_agent"}
        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock
        ) as mf:
            results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert not any('"tool_data"' in r for r in results)
        mf.assert_not_called()

    async def test_custom_event_forwarded_verbatim(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        events = [((), "custom", {"progress": "thinking"})]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert 'data: {"progress": "thinking"}\n\n' in results

    async def test_two_tuple_event_handled_without_crash(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        events = [("custom", {"progress": "two-tuple"})]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert 'data: {"progress": "two-tuple"}\n\n' in results
        assert results[-1] == "data: [DONE]\n\n"

    async def test_malformed_tuple_length_skipped(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        events = [("single_element",)]
        cfg = {"configurable": {}, "agent_name": "comms_agent"}
        results = await _drain(execute_graph_streaming(_streaming_graph(events), {}, cfg))
        assert results[-1] == "data: [DONE]\n\n"
        # nothing emitted before the terminal frames.
        assert len(results) == 2
