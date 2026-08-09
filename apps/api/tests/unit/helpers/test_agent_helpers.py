"""Comprehensive tests for app/helpers/agent_helpers.py."""

from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
import pytest

from app.constants.cache import CUSTOM_INT_METADATA_TTL, HANDOFF_METADATA_CACHE_PREFIX
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
)
from app.helpers.agent_helpers import (
    _build_agent_callbacks,
    _inherit_from_parent_configurable,
    _json_safe_tool_result,
    _resolve_model_config,
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
        assert result == {"integration_id": "github", "icon_url": None}
        # The cache is read with the exact prefixed, lowercased key.
        mock_get_cache.assert_awaited_once_with(f"{HANDOFF_METADATA_CACHE_PREFIX}:github")

    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_falsy_cached_value_returns_empty(self, mock_lookup, mock_get_cache):
        """A cached falsy (but not None) value is a negative cache hit."""
        mock_get_cache.return_value = 0

        result = await get_handoff_metadata("nonexistent")
        assert result == {}
        mock_lookup.assert_called_once_with("nonexistent")

    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_platform_integration_match_by_id(self, mock_lookup):
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("github")
        assert result == {
            "icon_url": None,
            "integration_id": "github",
            "integration_name": "GitHub",
        }

    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_platform_integration_match_by_short_name(self, mock_lookup):
        # The registry's get_subagent_by_id resolves short_name itself —
        # the mock just returns the same Subagent regardless of input.
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("gh")
        assert result["integration_name"] == "GitHub"

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.get_subagent_by_id")
    async def test_lookup_is_case_insensitive(self, mock_lookup, mock_log):
        """clean_id is lowercased before the registry lookup."""
        mock_lookup.return_value = _make_subagent("github", "gh", "GitHub")

        result = await get_handoff_metadata("GitHub")
        mock_lookup.assert_called_once_with("github")
        assert result["integration_id"] == "github"
        # Platform match tags the event.
        mock_log.set.assert_called_once_with(integration_type="platform")

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_custom_integration_found_in_db(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache, mock_log
    ):
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(
            return_value=_integration("custom_mymcp", "MyMCP", "https://icon.png")
        )

        result = await get_handoff_metadata("custom_mymcp")
        assert result == {
            "icon_url": "https://icon.png",
            "integration_id": "custom_mymcp",
            "integration_name": "MyMCP",
        }
        mock_log.set.assert_called_once_with(integration_type="custom")
        # The cache is written with the exact metadata and the custom TTL.
        mock_set_cache.assert_awaited_once_with(
            f"{HANDOFF_METADATA_CACHE_PREFIX}:custom_mymcp",
            {
                "icon_url": "https://icon.png",
                "integration_id": "custom_mymcp",
                "integration_name": "MyMCP",
            },
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_miss_caches_negative_result(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache
    ):
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)

        result = await get_handoff_metadata("absent")

        assert result == {}
        # Repository is queried with the cleaned, lowercased id.
        mock_repo.find_by_id_prefix_or_name.assert_awaited_once_with("absent")
        # Negative result cached so the lookup is not repeated.
        mock_set_cache.assert_awaited_once_with(
            f"{HANDOFF_METADATA_CACHE_PREFIX}:absent",
            {},
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.set_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_cache", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.integration_repository")
    @patch("app.helpers.agent_helpers.get_subagent_by_id", return_value=None)
    async def test_custom_integration_db_error_returns_empty(
        self, mock_lookup, mock_repo, mock_get_cache, mock_set_cache, mock_log
    ):
        mock_get_cache.return_value = None
        mock_repo.find_by_id_prefix_or_name = AsyncMock(side_effect=Exception("DB failure"))

        result = await get_handoff_metadata("broken")
        assert result == {}
        # Failure is loud: a warning with the error details is logged.
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.args[0] == "Failed to lookup handoff metadata"
        assert mock_log.warning.call_args.kwargs["error"] == "DB failure"
        assert mock_log.warning.call_args.kwargs["error_type"] == "Exception"
        # Nothing is cached on failure.
        mock_set_cache.assert_not_awaited()

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
# _build_agent_callbacks
# ---------------------------------------------------------------------------


class TestBuildAgentCallbacks:
    @patch("app.helpers.agent_helpers.build_langfuse_callback")
    @patch("app.helpers.agent_helpers.PostHogCallbackHandler")
    @patch("app.helpers.agent_helpers.providers")
    def test_exact_callback_order_and_posthog_args(self, mock_providers, mock_ph, mock_langfuse):
        """All three callback sources present: posthog, langfuse, usage — in order,
        with the exact PostHog construction args."""
        client = MagicMock()
        mock_providers.is_available.return_value = True
        mock_providers.get.return_value = client
        langfuse_handler = MagicMock()
        mock_langfuse.return_value = langfuse_handler
        usage_cb = MagicMock()

        callbacks = _build_agent_callbacks(CONV_ID, FAKE_USER, "comms_agent", usage_cb)

        mock_providers.is_available.assert_called_once_with("posthog")
        mock_providers.get.assert_called_once_with("posthog")
        mock_ph.assert_called_once_with(
            client=client,
            distinct_id=USER_ID,
            properties={"conversation_id": CONV_ID, "agent_name": "comms_agent"},
            privacy_mode=False,
        )
        assert callbacks == [mock_ph.return_value, langfuse_handler, usage_cb]

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.PostHogCallbackHandler")
    @patch("app.helpers.agent_helpers.providers")
    def test_no_posthog_when_unavailable(self, mock_providers, mock_ph, mock_langfuse):
        mock_providers.is_available.return_value = False

        callbacks = _build_agent_callbacks(CONV_ID, FAKE_USER, "comms_agent", None)

        mock_providers.is_available.assert_called_once_with("posthog")
        mock_providers.get.assert_not_called()
        mock_ph.assert_not_called()
        assert callbacks == []

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.PostHogCallbackHandler")
    @patch("app.helpers.agent_helpers.providers")
    def test_no_usage_callback_when_none(self, mock_providers, mock_ph, mock_langfuse):
        """usage_metadata_callback=None must not be appended."""
        client = MagicMock()
        mock_providers.is_available.return_value = True
        mock_providers.get.return_value = client

        callbacks = _build_agent_callbacks(CONV_ID, FAKE_USER, "comms_agent", None)

        assert callbacks == [mock_ph.return_value]

    @patch("app.helpers.agent_helpers.build_langfuse_callback")
    @patch("app.helpers.agent_helpers.PostHogCallbackHandler")
    @patch("app.helpers.agent_helpers.providers")
    def test_no_langfuse_when_unconfigured(self, mock_providers, mock_ph, mock_langfuse):
        mock_providers.is_available.return_value = False
        mock_langfuse.return_value = None
        usage_cb = MagicMock()

        callbacks = _build_agent_callbacks(CONV_ID, FAKE_USER, "comms_agent", usage_cb)

        assert callbacks == [usage_cb]


# ---------------------------------------------------------------------------
# _resolve_model_config
# ---------------------------------------------------------------------------


class TestResolveModelConfig:
    @patch("app.helpers.agent_helpers.log")
    def test_user_model_config_exact_tuple(self, mock_log):
        model_cfg = MagicMock()
        model_cfg.provider_model_name = "gpt-4o"
        model_cfg.inference_provider.value = "openai"
        model_cfg.max_tokens = 9000

        result = _resolve_model_config(model_cfg)

        assert result == ("gpt-4o", "openai", 9000)
        mock_log.set.assert_called_once_with(model_config_source="user_selected")

    @patch("app.helpers.agent_helpers.log")
    def test_no_config_uses_defaults(self, mock_log):
        result = _resolve_model_config(None)

        assert result == (DEFAULT_MODEL_NAME, DEFAULT_LLM_PROVIDER, DEFAULT_MAX_TOKENS)
        mock_log.set.assert_called_once_with(model_config_source="default")


# ---------------------------------------------------------------------------
# _inherit_from_parent_configurable
# ---------------------------------------------------------------------------


def _full_current() -> dict[str, object]:
    """The complete AgentConfigurable `current` dict build_agent_config builds."""
    return {
        "provider": "openai",
        "max_tokens": 9000,
        "model_name": "gpt-4o",
        "conversation_id": "child-conv",
        "selected_tool": "child-tool",
        "tool_category": "child-cat",
        "subagent_id": "child-sub",
        "vfs_session_id": "child-vfs",
        "active_todo_id": "child-todo",
        "conversation_source": "web",
        "user_messages": ["child paraphrase"],
        "execution_mode": "interactive",
    }


class TestInheritFromParentConfigurable:
    def test_no_parent_returns_current_with_null_stream_id(self):
        current = _full_current()

        merged = _inherit_from_parent_configurable(None, current)

        assert merged == {**_full_current(), "stream_id": None}

    def test_exact_merge_semantics(self):
        """One full parent against one full child: model fields + conversation_id +
        user_messages override; fallback keys stay on the child; stream_id and
        model_kwargs come from the parent."""
        base = {
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3-5-sonnet",
            "conversation_id": "true-conv",
            "user_messages": ["parent verbatim"],
            "selected_tool": "parent-tool",
            "tool_category": "parent-cat",
            "subagent_id": "parent-sub",
            "vfs_session_id": "parent-vfs",
            "active_todo_id": "parent-todo",
            "execution_mode": "background",
            "conversation_source": "telegram",
            "stream_id": "parent-stream",
            "model_kwargs": {"route": "claude-3-5-sonnet"},
        }

        merged = _inherit_from_parent_configurable(base, _full_current())

        assert merged == {
            **_full_current(),
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3-5-sonnet",
            "conversation_id": "true-conv",
            "user_messages": ["parent verbatim"],
            "stream_id": "parent-stream",
            "model_kwargs": {"route": "claude-3-5-sonnet"},
        }

    def test_blank_parent_conversation_id_keeps_child(self):
        """conversation_id inheritance is `or`-based: a blank parent value must
        not clobber the child's."""
        base = {"conversation_id": "", "user_messages": []}

        merged = _inherit_from_parent_configurable(base, _full_current())

        assert merged["conversation_id"] == "child-conv"
        assert merged["user_messages"] == ["child paraphrase"]

    def test_execution_mode_parent_fills_blank_only(self):
        merged = _inherit_from_parent_configurable(
            {"execution_mode": "background"}, {**_full_current(), "execution_mode": None}
        )
        assert merged["execution_mode"] == "background"

        no_mode = _inherit_from_parent_configurable({}, _full_current())
        assert no_mode["execution_mode"] == "interactive"

    def test_model_kwargs_inherited_only_when_present(self):
        with_kwargs = _inherit_from_parent_configurable(
            {"model_kwargs": {"route": "x"}}, _full_current()
        )
        assert with_kwargs["model_kwargs"] == {"route": "x"}

        without = _inherit_from_parent_configurable({}, _full_current())
        assert "model_kwargs" not in without

    def test_parent_without_model_keys_keeps_child_values(self):
        """The model-field inheritance defaults to the child's resolved value:
        a parent that lacks provider/max_tokens/model_name must not blank them."""
        base = {"conversation_id": "true-conv"}

        merged = _inherit_from_parent_configurable(base, _full_current())

        assert merged["provider"] == "openai"
        assert merged["max_tokens"] == 9000
        assert merged["model_name"] == "gpt-4o"

    def test_stream_id_always_from_parent(self):
        with_stream = _inherit_from_parent_configurable({"stream_id": "s1"}, _full_current())
        assert with_stream["stream_id"] == "s1"

        without = _inherit_from_parent_configurable({}, _full_current())
        assert without["stream_id"] is None


# ---------------------------------------------------------------------------
# _json_safe_tool_result
# ---------------------------------------------------------------------------


class TestJsonSafeToolResult:
    def test_media_content_is_text_extracted(self):
        content = [{"type": "image", "base64": "AAA", "mime_type": "image/png"}]

        result = _json_safe_tool_result(content)

        # Media blocks never reach the SSE payload: text extraction drops them.
        assert result == ""

    def test_serializable_content_passes_through(self):
        content = {"result": "ok", "nested": [1, 2]}

        assert _json_safe_tool_result(content) is content

    def test_model_dump_fallback(self):
        class WithDump:
            def model_dump(self):
                return {"a": 1}

        assert _json_safe_tool_result(WithDump()) == {"a": 1}

    def test_dict_fallback(self):
        class WithDict:
            def __init__(self) -> None:
                self.a = 1

        assert _json_safe_tool_result(WithDict()) == {"a": 1}

    def test_str_fallback(self):
        class Opaque:
            __slots__ = ()

            def __repr__(self) -> str:
                return "<opaque>"

        assert _json_safe_tool_result(Opaque()) == "<opaque>"


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

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_exact_configurable_and_metadata(self, mock_providers, mock_langfuse) -> None:
        """One rich call pins every key of the configurable bag, the trace
        metadata, and the recursion limit — parent overrides, child wins,
        pass-throughs, and timezone resolution all at once."""
        mock_providers.get.return_value = None
        model_cfg = MagicMock()
        model_cfg.provider_model_name = "gpt-4o"
        model_cfg.inference_provider.value = "openai"
        model_cfg.max_tokens = 9000
        base = {
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3-5-sonnet",
            "conversation_id": "true-conv-1",
            "user_messages": ["parent verbatim"],
            "selected_tool": "parent-tool",
            "tool_category": "parent-cat",
            "subagent_id": "parent-sub",
            "vfs_session_id": "parent-vfs",
            "active_todo_id": "parent-todo",
            "execution_mode": "background",
            "conversation_source": "telegram",
            "stream_id": "parent-stream",
            "user_timezone": "America/New_York",
            "root_request_id": "root-42",
            "plan_type": "todo",
            "langfuse_trace_id": "trace-parent",
            "langfuse_tags": ["tag-parent"],
            "model_kwargs": {"route": "anthropic-claude-3-5-sonnet"},
        }

        config = build_agent_config(
            conversation_id="child-conv",
            user={**FAKE_USER, "timezone": "  Asia/Kolkata  "},
            agent_name="executor",
            user_model_config=model_cfg,
            thread_id="child-thread",
            base_configurable=base,
            selected_tool="child-tool",
            tool_category="child-cat",
            subagent_id="child-sub",
            vfs_session_id="child-vfs",
            active_todo_id="child-todo",
            execution_mode="interactive",
            source="web",
            user_messages=["child paraphrase"],
            langfuse_trace_id="trace-child",
            langfuse_tags=["tag-child"],
            recursion_limit=1234,
        )

        assert config["configurable"] == {
            "thread_id": "child-thread",
            # Parent overrides the child's wrapped conversation id.
            "conversation_id": "true-conv-1",
            # Parent overrides the child's agent-authored paraphrase.
            "user_messages": ["parent verbatim"],
            "user_id": USER_ID,
            "email": "test@example.com",
            "user_name": "Test User",
            # User's own timezone wins over the parent's reconstructed one, and
            # surrounding whitespace is stripped.
            "user_timezone": "Asia/Kolkata",
            "root_request_id": "root-42",
            # Parent overrides the user model config triple.
            "provider": "anthropic",
            "max_tokens": 4000,
            "model_name": "claude-3-5-sonnet",
            "model": "claude-3-5-sonnet",
            # Child wins for fallback keys.
            "selected_tool": "child-tool",
            "tool_category": "child-cat",
            "subagent_id": "child-sub",
            "vfs_session_id": "child-vfs",
            "stream_id": "parent-stream",
            "active_todo_id": "child-todo",
            "execution_mode": "interactive",
            "conversation_source": "web",
            "source_category": "ui",
            "plan_type": "todo",
            # Explicit kwargs beat inherited trace values.
            "langfuse_trace_id": "trace-child",
            "langfuse_tags": ["tag-child"],
            "model_kwargs": {"route": "anthropic-claude-3-5-sonnet"},
        }
        assert config["metadata"] == {
            "user_id": USER_ID,
            "source_category": "ui",
            "source_channel": "web",
            "langfuse_trace_id": "trace-child",
            "langfuse_session_id": "child-conv",
            "langfuse_user_id": USER_ID,
            "langfuse_tags": ["tag-child"],
        }
        assert config["recursion_limit"] == 1234
        assert config["agent_name"] == "executor"
        assert config["callbacks"] == []

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_exact_defaults_configurable(self, mock_providers, mock_langfuse) -> None:
        """No user model config, no parent, no source: model defaults, UTC,
        background channel, and a fresh root_request_id."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
        )

        configurable = config["configurable"]
        # root_request_id is a fresh UUID4 when no parent provides one.
        uuid.UUID(configurable.pop("root_request_id"))
        uuid.UUID(
            build_agent_config(conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent")[
                "configurable"
            ]["root_request_id"]
        )
        assert configurable == {
            "thread_id": CONV_ID,
            "conversation_id": CONV_ID,
            "user_messages": None,
            "user_id": USER_ID,
            "email": "test@example.com",
            "user_name": "Test User",
            "user_timezone": "UTC",
            "provider": DEFAULT_LLM_PROVIDER,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "model_name": DEFAULT_MODEL_NAME,
            "model": DEFAULT_MODEL_NAME,
            "selected_tool": None,
            "tool_category": None,
            "subagent_id": None,
            "vfs_session_id": None,
            "stream_id": None,
            "active_todo_id": None,
            "execution_mode": "interactive",
            "conversation_source": None,
            "source_category": "bg",
        }
        assert config["metadata"] == {
            "user_id": USER_ID,
            "source_category": "bg",
            "source_channel": "background",
        }
        assert config["recursion_limit"] == AGENT_RECURSION_LIMIT

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_explicit_empty_tags_clears_inherited_tags(self, mock_providers, mock_langfuse) -> None:
        """langfuse_tags=[] is a deliberate clear — the key must disappear from
        both the configurable and the metadata."""
        mock_providers.get.return_value = None
        base = {
            "langfuse_trace_id": "trace-parent",
            "langfuse_tags": ["tag-parent"],
        }

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
            base_configurable=base,
            langfuse_tags=[],
        )

        assert config["configurable"]["langfuse_trace_id"] == "trace-parent"
        assert "langfuse_tags" not in config["configurable"]
        assert "langfuse_tags" not in config["metadata"]

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_trace_id_inherited_when_kwarg_omitted(self, mock_providers, mock_langfuse) -> None:
        """No explicit langfuse_trace_id → the parent's is inherited into the
        configurable AND the metadata."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={"langfuse_trace_id": "trace-parent"},
        )

        assert config["configurable"]["langfuse_trace_id"] == "trace-parent"
        assert config["metadata"]["langfuse_trace_id"] == "trace-parent"
        assert config["metadata"]["langfuse_session_id"] == CONV_ID
        assert config["metadata"]["langfuse_user_id"] == USER_ID

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_bare_user_dict_defaults_email_and_name(self, mock_providers, mock_langfuse) -> None:
        """Child agents reconstruct a bare user dict; missing email/name keys
        must yield None / "" rather than raise."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user={"user_id": "u1"},
            agent_name="executor",
        )

        assert config["configurable"]["user_id"] == "u1"
        assert config["configurable"]["email"] is None
        assert config["configurable"]["user_name"] == ""
        assert config["metadata"]["user_id"] == "u1"

    @patch("app.helpers.agent_helpers._build_agent_callbacks", return_value=["cb"])
    @patch("app.helpers.agent_helpers.providers")
    def test_callback_builder_receives_exact_args(self, mock_providers, mock_builder) -> None:
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="comms_agent",
        )

        mock_builder.assert_called_once_with(CONV_ID, FAKE_USER, "comms_agent", None)
        assert config["callbacks"] == ["cb"]

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_langfuse_tags_inherited_when_kwarg_omitted(self, mock_providers, mock_langfuse) -> None:
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={"langfuse_tags": ["tag-parent"]},
        )

        assert config["configurable"]["langfuse_tags"] == ["tag-parent"]
        # Tags reach the trace metadata only alongside a trace id.
        assert "langfuse_tags" not in config["metadata"]

    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    @patch("app.helpers.agent_helpers.providers")
    def test_blank_parent_timezone_falls_back_to_utc(self, mock_providers, mock_langfuse) -> None:
        """A parent's blank user_timezone must not survive as the home zone."""
        mock_providers.get.return_value = None

        config = build_agent_config(
            conversation_id=CONV_ID,
            user=FAKE_USER,
            agent_name="executor",
            base_configurable={"user_timezone": ""},
        )

        assert config["configurable"]["user_timezone"] == "UTC"


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

    def test_exact_state_shape(self):
        """Every static key of the initial state, plus an ISO-8601 UTC now."""
        request = MagicMock()
        request.message = "Hello"
        request.selectedTool = "toolA"
        request.selectedWorkflow = "workflow1"
        request.selectedCalendarEvent = "event123"

        state = build_initial_state(request, USER_ID, CONV_ID, ["msg1"])

        expected = {
            "query": "Hello",
            "intent": "Hello",
            "messages": ["msg1"],
            "memory_user_id": USER_ID,
            "conversation_id": CONV_ID,
            "integration_usernames": {},
            "selected_tool": "toolA",
            "selected_workflow": "workflow1",
            "selected_calendar_event": "event123",
        }
        for key, value in expected.items():
            assert state[key] == value
        assert set(state) == set(expected) | {"current_datetime"}
        timestamp = datetime.fromisoformat(state["current_datetime"])
        assert timestamp.tzinfo is not None

    def test_trigger_context_binds_active_todo_and_mode(self):
        request = MagicMock()
        request.message = "Trigger"
        request.selectedTool = None
        request.selectedWorkflow = None
        request.selectedCalendarEvent = None

        state = build_initial_state(
            request,
            USER_ID,
            CONV_ID,
            [],
            trigger_context={"active_todo_id": "todo-9", "execution_mode": "background"},
        )

        assert state["active_todo_id"] == "todo-9"
        assert state["execution_mode"] == "background"

    def test_trigger_context_todo_alias(self):
        """Schedulers may pass `todo_id`; it binds to the same active_todo_id key."""
        request = MagicMock()
        request.message = "Trigger"
        request.selectedTool = None
        request.selectedWorkflow = None
        request.selectedCalendarEvent = None

        state = build_initial_state(
            request, USER_ID, CONV_ID, [], trigger_context={"todo_id": "todo-9"}
        )

        assert state["active_todo_id"] == "todo-9"
        assert "execution_mode" not in state

    def test_trigger_context_without_todo_keys_adds_none(self):
        request = MagicMock()
        request.message = "Trigger"
        request.selectedTool = None
        request.selectedWorkflow = None
        request.selectedCalendarEvent = None

        state = build_initial_state(
            request, USER_ID, CONV_ID, [], trigger_context={"trigger": "reminder"}
        )

        assert state["trigger_context"] == {"trigger": "reminder"}
        assert "active_todo_id" not in state
        assert "execution_mode" not in state


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
        # The astream call carries the exact modes, config, and subgraph flag.
        graph.astream.assert_called_once_with(
            {"query": "test"},
            stream_mode=["messages", "custom", "updates"],
            config={"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}},
            subgraphs=True,
        )

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
        assert tool_data["tool_data"] == [{"tool_name": "custom_tool"}]
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
            "integration_name": "GitHub",
        }
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        tc = {"id": "tc1", "name": "handoff", "args": {"subagent_id": "github"}}
        msg = AIMessage(content="", tool_calls=[tc])
        # langchain normalizes tool_calls dicts (adds "type"); the loop formats
        # the normalized dict, so pin the exact object handed to the formatter.
        expected_tc = msg.tool_calls[0]

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

        mock_handoff.assert_awaited_once_with("github")
        # The resolved handoff metadata must be forwarded into the formatted entry.
        mock_format.assert_awaited_once_with(
            expected_tc,
            icon_url="https://icon.png",
            integration_id="github",
            integration_name="GitHub",
            user_id=USER_ID,
        )
        assert tool_data["tool_data"] == [{"tool_name": "handoff", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_updates_regular_tool_calls_thread_user_id(self, mock_format):
        """Non-handoff tool calls are formatted with the originating user_id (so
        format_tool_call_entry can resolve MCP metadata) and appended."""
        mock_format.return_value = {"tool_name": "custom_tool", "data": {}}

        msg = AIMessage(content="", tool_calls=[{"id": "tc2", "name": "custom_tool", "args": {}}])
        expected_tc = msg.tool_calls[0]

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

        mock_format.assert_awaited_once_with(
            expected_tc,
            icon_url=None,
            integration_id=None,
            integration_name=None,
            user_id=USER_ID,
        )
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

    async def test_exact_todo_progress_entry_shape(self):
        """Snapshots accumulate by source and are injected as one tool_data entry
        with an ISO timestamp."""
        events = [
            ((), "custom", {"todo_progress": {"source": "executor", "count": 3}}),
            ((), "custom", {"todo_progress": {"source": "scheduler", "count": 1}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.process_custom_event_for_tools",
            return_value={},
        ):
            _, tool_data = await execute_graph_silent(
                graph,
                {},
                {"configurable": {"user_id": USER_ID}},
            )

        assert len(tool_data["tool_data"]) == 1
        entry = tool_data["tool_data"][0]
        assert entry["tool_name"] == "todo_progress"
        assert entry["data"] == {
            "executor": {"source": "executor", "count": 3},
            "scheduler": {"source": "scheduler", "count": 1},
        }
        datetime.fromisoformat(entry["timestamp"])

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_handoff_without_subagent_id_skips_lookup(self, mock_handoff, mock_format):
        """A handoff tool call with an empty subagent_id must not trigger a
        metadata lookup; formatting proceeds with an empty metadata bag."""
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        msg = MagicMock()
        msg.tool_calls = [{"id": "tc1", "name": "handoff", "args": {}}]

        events = [((), "updates", {"agent": {"messages": [msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_handoff.assert_not_awaited()
        assert mock_format.await_args.kwargs["icon_url"] is None
        assert mock_format.await_args.kwargs["integration_id"] is None
        assert mock_format.await_args.kwargs["integration_name"] is None
        assert tool_data["tool_data"] == [{"tool_name": "handoff", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_tool_call_without_id_is_skipped(self, mock_format):
        msg = MagicMock()
        msg.tool_calls = [{"name": "some_tool", "args": {}}]

        events = [((), "updates", {"agent": {"messages": [msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_format.assert_not_awaited()
        assert tool_data["tool_data"] == []

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_format_returning_none_is_not_emitted(self, mock_format):
        """format_tool_call_entry returning None (unresolvable tool) must not
        append anything nor mark the call emitted."""
        mock_format.return_value = None

        msg = MagicMock()
        msg.tool_calls = [{"id": "tc1", "name": "some_tool", "args": {}}]

        events = [((), "updates", {"agent": {"messages": [msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        assert tool_data["tool_data"] == []

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_message_without_tool_calls_attribute_is_skipped(self, mock_format):
        msg = SimpleNamespace(response_metadata=None)

        events = [((), "updates", {"agent": {"messages": [msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_format.assert_not_awaited()
        assert tool_data["tool_data"] == []

    async def test_non_ai_message_chunk_is_ignored(self):
        chunk = HumanMessage(content="human text")

        events = [((), "messages", (chunk, {"agent_name": "comms_agent"}))]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, tool_data = await execute_graph_silent(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
        )

        assert msg == ""
        assert tool_data == {"tool_data": []}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_non_dict_state_update_is_skipped(self, mock_format):
        events = [((), "updates", {"agent": "not-a-dict"})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_format.assert_not_awaited()
        assert tool_data == {"tool_data": []}

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools", return_value={})
    async def test_custom_event_without_todo_progress_is_inert(self, mock_process):
        events = [((), "custom", {"follow_up_actions": ["a"]})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_process.assert_called_once_with({"follow_up_actions": ["a"]})
        assert tool_data == {"tool_data": []}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_non_agent_update_then_agent_update_emits(self, mock_format):
        """A non-agent node in the SAME payload as the agent node must be
        skipped, not terminate the payload loop: the agent node still emits."""
        mock_format.return_value = {"tool_name": "t", "data": {}}

        hook_msg = AIMessage(content="", tool_calls=[{"id": "old", "name": "t", "args": {}}])
        agent_msg = AIMessage(content="", tool_calls=[{"id": "new", "name": "t", "args": {}}])

        events = [
            ((), "updates", {"pre_model_hook": {"messages": [hook_msg]}, "agent": {"messages": [agent_msg]}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        assert tool_data["tool_data"] == [{"tool_name": "t", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_non_dict_state_update_containing_messages_word(self, mock_format):
        """A non-dict state update whose repr contains the word 'messages' must
        still be skipped (an `or` in the guard would crash on it)."""
        events = [((), "updates", {"agent": "state with messages payload"})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_format.assert_not_awaited()
        assert tool_data == {"tool_data": []}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_msg_without_tool_calls_then_valid_msg_in_same_update(self, mock_format):
        """A message without tool_calls is skipped individually — the next
        message in the same update still emits."""
        mock_format.return_value = {"tool_name": "t", "data": {}}

        bare = SimpleNamespace(response_metadata=None)
        agent_msg = AIMessage(content="", tool_calls=[{"id": "tc2", "name": "t", "args": {}}])

        events = [((), "updates", {"agent": {"messages": [bare, agent_msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        assert tool_data["tool_data"] == [{"tool_name": "t", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_tool_call_without_id_then_valid_tool_call(self, mock_format):
        """A tool call without an id is skipped individually — the following
        one still emits."""
        mock_format.return_value = {"tool_name": "t", "data": {}}

        agent_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc1", "name": "t", "args": {}},
            ],
        )
        # An id-less tool call cannot be built through pydantic; append it raw.
        # It must come FIRST so a `break` on it would skip the valid call.
        agent_msg.tool_calls.insert(0, {"name": "no_id", "args": {}})

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_format.assert_awaited_once()
        assert tool_data["tool_data"] == [{"tool_name": "t", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_plan_tasks_skip_then_normal_tool_emits(self, mock_format):
        """plan_tasks suppression is per-tool-call: a normal tool call after it
        still emits."""
        mock_format.return_value = {"tool_name": "t", "data": {}}

        agent_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc_plan", "name": "plan_tasks", "args": {}},
                {"id": "tc_norm", "name": "t", "args": {}},
            ],
        )

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        assert tool_data["tool_data"] == [{"tool_name": "t", "data": {}}]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_handoff_without_args_key_skips_lookup(self, mock_handoff, mock_format):
        """A handoff tool call with no args dict must not crash: args defaults
        to {}, subagent_id stays empty, and the lookup is skipped."""
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        agent_msg = AIMessage(
            content="", tool_calls=[{"id": "tc1", "name": "handoff", "args": {}}]
        )
        # An args-less tool call cannot be built through pydantic; strip it raw.
        del agent_msg.tool_calls[0]["args"]

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        mock_handoff.assert_not_awaited()
        assert tool_data["tool_data"] == [{"tool_name": "handoff", "data": {}}]

    async def test_updates_then_messages_accumulates(self):
        """The updates branch must not terminate the stream: a following
        messages chunk still accumulates into complete_message."""
        from langchain_core.messages import AIMessageChunk as AIMC

        tool_msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "t", "args": {}}])
        chunk = MagicMock(spec=AIMC)
        chunk.text = "Hello"
        chunk.content = "Hello"

        events = [
            ((), "updates", {"agent": {"messages": [tool_msg]}}),
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "t"},
        ):
            msg, _ = await execute_graph_silent(
                graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
            )

        assert msg == "Hello"

    async def test_silent_chunk_then_normal_chunk_accumulates(self):
        """A silent chunk is skipped individually — the following normal chunk
        still accumulates."""
        from langchain_core.messages import AIMessageChunk as AIMC

        silent = MagicMock(spec=AIMC)
        silent.text = "hidden"
        silent.content = "hidden"
        normal = MagicMock(spec=AIMC)
        normal.text = "Hello"
        normal.content = "Hello"

        events = [
            ((), "messages", (silent, {"agent_name": "comms_agent", "silent": True})),
            ((), "messages", (normal, {"agent_name": "comms_agent"})),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, _ = await execute_graph_silent(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
        )

        assert msg == "Hello"

    async def test_todo_progress_without_source_defaults_to_executor(self):
        """A todo_progress snapshot without a source key lands under 'executor'."""
        events = [
            ((), "custom", {"todo_progress": {"count": 7}}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.process_custom_event_for_tools",
            return_value={},
        ):
            _, tool_data = await execute_graph_silent(
                graph, {}, {"configurable": {"user_id": USER_ID}}
            )

        assert tool_data["tool_data"][0]["data"] == {"executor": {"count": 7}}

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools")
    async def test_two_custom_events_accumulate_tool_data(self, mock_process):
        """The non-tool_data merge loop must never clobber the accumulated
        tool_data list: entries from both events survive."""
        mock_process.side_effect = [
            {"tool_data": [{"tool_name": "a"}]},
            {"tool_data": [{"tool_name": "b"}]},
        ]

        events = [
            ((), "custom", {"x": 1}),
            ((), "custom", {"x": 2}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        )

        assert tool_data["tool_data"] == [{"tool_name": "a"}, {"tool_name": "b"}]

    async def test_todo_progress_timestamp_is_utc_aware(self):
        """The injected todo_progress entry's timestamp carries a UTC offset."""
        events = [((), "custom", {"todo_progress": {"source": "executor", "count": 1}})]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.process_custom_event_for_tools",
            return_value={},
        ):
            _, tool_data = await execute_graph_silent(
                graph, {}, {"configurable": {"user_id": USER_ID}}
            )

        timestamp = tool_data["tool_data"][0]["timestamp"]
        assert timestamp.endswith("+00:00")


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

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_exact_sse_sequence_for_comms_messages(self, mock_sm):
        """A comms_agent message stream yields the exact SSE frames in order:
        response deltas, then the nostream summary, then DONE."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk1 = AIMessageChunk(content="Hello ")
        chunk2 = AIMessageChunk(content="world")

        events = [
            ((), "messages", (chunk1, {"agent_name": "comms_agent"})),
            ((), "messages", (chunk2, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"response": "Hello "}\n\n',
            'data: {"response": "world"}\n\n',
            'nostream: {"complete_message": "Hello world"}',
            "data: [DONE]\n\n",
        ]
        graph.astream.assert_called_once_with(
            {},
            stream_mode=["messages", "custom", "updates"],
            config={"agent_name": "comms_agent", "configurable": {}},
            subgraphs=True,
        )

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_non_comms_agent_content_not_streamed(self, mock_sm):
        """Executor chunks must not be streamed as responses (comms owns the
        SSE) and never accumulate into complete_message."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk = AIMessageChunk(content="executor text")

        events = [((), "messages", (chunk, {"agent_name": "executor_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "executor_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_silent_chunk_not_streamed(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk = AIMessageChunk(content="hidden")

        events = [((), "messages", (chunk, {"agent_name": "comms_agent", "silent": True}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_silent_chunk_then_normal_chunk_streams(self, mock_sm):
        """A silent chunk is skipped individually — the following normal chunk
        still streams and accumulates."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        silent = AIMessageChunk(content="hidden")
        normal = AIMessageChunk(content="Hello")

        events = [
            ((), "messages", (silent, {"agent_name": "comms_agent", "silent": True})),
            ((), "messages", (normal, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"response": "Hello"}\n\n',
            'nostream: {"complete_message": "Hello"}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_exact_tool_data_yield(self, mock_sm, mock_handoff, mock_format):
        """The agent node's tool calls are streamed as one exact tool_data frame."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        entry = {"tool_name": "web_search", "data": {"query": "x"}}
        mock_format.return_value = entry

        msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "x"}}])

        events = [((), "updates", {"agent": {"messages": [msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        # user_id is threaded through so MCP metadata can be resolved.
        assert mock_format.await_args.kwargs["user_id"] == USER_ID
        # Non-handoff calls never hit the handoff lookup.
        mock_handoff.assert_not_awaited()
        assert results == [
            f"data: {json.dumps({'tool_data': entry})}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_model_fallback_frame_emitted_once(self, mock_sm, mock_format):
        """A gaia_fell_back flag on an agent-node message yields one exact
        ModelFallbackFrame, even when repeated across updates."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        msg = AIMessage(
            content="",
            tool_calls=[],
            response_metadata={"gaia_fell_back": True, "gaia_fallback_model": "gpt-4-mini"},
        )

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "updates", {"agent": {"messages": [msg]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"model_fallback": {"model": "gpt-4-mini"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_tool_output_yielded_when_claimed(self, mock_sm, mock_claim):
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        tool_msg = ToolMessage(content="result", tool_call_id="tc1")

        events = [((), "messages", (tool_msg, {"agent_name": "comms_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"stream_id": "s1"}}
        ):
            results.append(s)

        mock_claim.assert_called_once_with("s1", "tc1")
        assert results == [
            'data: {"tool_output": {"tool_call_id": "tc1", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=False)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_tool_output_suppressed_when_echo(self, mock_sm, mock_claim):
        """A tool result whose stream does not own it (echo from a subagent's
        detached run) must not be streamed again."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        tool_msg = ToolMessage(content="result", tool_call_id="tc1")

        events = [((), "messages", (tool_msg, {"agent_name": "comms_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_todo_tool_outputs_suppressed(self, mock_sm, mock_claim):
        """Todo tools already stream todo_progress; their raw ToolMessage
        results must not produce tool_output frames."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        by_name = ToolMessage(content="plan", tool_call_id="tc1", name="plan_tasks")
        by_name_update = ToolMessage(content="update", tool_call_id="tc1b", name="update_tasks")
        by_flag = ToolMessage(
            content="update",
            tool_call_id="tc2",
            additional_kwargs={"todo_tool": True},
        )

        events = [
            ((), "messages", (by_name, {"agent_name": "comms_agent"})),
            ((), "messages", (by_name_update, {"agent_name": "comms_agent"})),
            ((), "messages", (by_flag, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_claim.assert_not_called()
        assert results == [
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_emitted_after_tool_result(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """An MCP App UI announced in updates is emitted as one mcp_app frame
        when the ToolMessage with the result arrives."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        tool_entry = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {
                "tool_call_id": "tc_app",
                "tool_name": "search_github",
                "inputs": {"q": "x"},
            },
            "mcp_ui": {"resource_uri": "/app"},
            "mcp_server_url": "https://mcp.example.com",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        mock_format.return_value = tool_entry
        mock_fetch.return_value = {
            "html": "<div>hi</div>",
            "csp": "override-csp",
            "permissions": ["camera"],
        }

        msg = AIMessage(content="", tool_calls=[{"id": "tc_app", "name": "search_github", "args": {}}])
        tool_msg = ToolMessage(content="result text", tool_call_id="tc_app")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        mock_fetch.assert_awaited_once_with(
            server_url="https://mcp.example.com",
            resource_uri="/app",
            user_id=USER_ID,
        )
        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_app",
                    "tool_name": "search_github",
                    "server_url": "https://mcp.example.com",
                    "resource_uri": "/app",
                    "html_content": "<div>hi</div>",
                    "tool_result": "result text",
                    "csp": "override-csp",
                    "permissions": ["camera"],
                    "tool_arguments": {"q": "x"},
                },
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        }
        assert results == [
            f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_app", "output": "result text"}}\n\n',
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_skipped_when_resource_has_no_html(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """A resource without html content must not emit an mcp_app frame (the
        tool_output frame still streams)."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {"tool_call_id": "tc_app", "tool_name": "t", "inputs": {}},
            "mcp_ui": {"resource_uri": "/app"},
            "mcp_server_url": "https://mcp.example.com",
            "timestamp": "t1",
        }
        mock_fetch.return_value = {"csp": "x"}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_app", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_app")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_fetch.assert_awaited_once()
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_app", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_custom_event_forwarded_verbatim(self, mock_sm):
        """Custom events are forwarded as-is with SSE framing."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        payload = {"follow_up_actions": ["a", "b"]}

        events = [((), "custom", payload)]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert results == [
            f"data: {json.dumps(payload)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_mcp_app_flow_via_custom_events(self, mock_sm, mock_fetch):
        """Custom MCP tools execute inside subagents: their tool_calls_data
        custom event buffers the app, and the tool_output custom event emits it
        with fallbacks to the buffered mcp_ui metadata."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "<div>sub</div>"}

        calls_event = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_sub",
                    "tool_name": "search_github",
                    "inputs": {"q": "x"},
                },
                "mcp_ui": {
                    "resource_uri": "/sub/app",
                    "csp": "default-src 'self'",
                    "permissions": ["clipboard-read"],
                },
                "mcp_server_url": "https://mcp2.example.com",
                "timestamp": "t1",
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_sub", "output": "sub result"}}

        events = [
            ((), "custom", calls_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        mock_fetch.assert_awaited_once_with(
            server_url="https://mcp2.example.com",
            resource_uri="/sub/app",
            user_id=USER_ID,
        )
        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_sub",
                    "tool_name": "search_github",
                    "server_url": "https://mcp2.example.com",
                    "resource_uri": "/sub/app",
                    "html_content": "<div>sub</div>",
                    "tool_result": "sub result",
                    "csp": "default-src 'self'",
                    "permissions": ["clipboard-read"],
                    "tool_arguments": {"q": "x"},
                },
                "timestamp": "t1",
            }
        }
        assert results == [
            f"data: {json.dumps(calls_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.record_interruption", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_cancellation_records_interruption_and_acks(self, mock_sm, mock_record):
        """Cancellation stops processing mid-stream, records the interruption,
        and acks the client with the accumulated message."""
        mock_sm.is_cancelled = AsyncMock(side_effect=[False, True])

        chunk = AIMessageChunk(content="partial")

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))
        config = {"agent_name": "comms_agent", "configurable": {"stream_id": "s1"}}

        results = []
        async for s in execute_graph_streaming(graph, {}, config):
            results.append(s)

        assert results == [
            'data: {"response": "partial"}\n\n',
            'nostream: {"complete_message": "partial", "cancelled": true}',
            "data: [DONE]\n\n",
        ]
        mock_record.assert_awaited_once_with(graph, config)
        mock_sm.is_cancelled.assert_awaited_with("s1")

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.record_interruption", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_record_interruption_failure_still_acks(self, mock_sm, mock_record, mock_log):
        """A failed interruption recording is logged loudly but the cancel ack
        must still reach the client."""
        mock_sm.is_cancelled = AsyncMock(side_effect=[False, True])
        mock_record.side_effect = Exception("boom")

        chunk = AIMessageChunk(content="partial")

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
            # A second event lets the loop observe the cancellation; without it
            # the async-for exhausts before is_cancelled is polled again.
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"stream_id": "s1"}}
        ):
            results.append(s)

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == "[AGENT] Failed to record interruption"
        assert mock_log.error.call_args.kwargs["error"] == "boom"
        assert mock_log.error.call_args.kwargs["error_type"] == "Exception"
        assert results == [
            'data: {"response": "partial"}\n\n',
            'nostream: {"complete_message": "partial", "cancelled": true}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_2_tuple_event_streams_content(self, mock_sm):
        """A 2-tuple (mode, payload) event must be handled, not dropped: its
        content still streams."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk = AIMessageChunk(content="Hello")

        events = [("messages", (chunk, {"agent_name": "comms_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"response": "Hello"}\n\n',
            'nostream: {"complete_message": "Hello"}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_unexpected_length_then_valid_event(self, mock_sm):
        """A malformed event is skipped individually — the following valid one
        still streams."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk = AIMessageChunk(content="Hello")

        events = [
            ("single_element",),
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"response": "Hello"}\n\n',
            'nostream: {"complete_message": "Hello"}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_non_agent_update_then_agent_update_emits(self, mock_sm, mock_format):
        """A non-agent node in the SAME payload as the agent node must be
        skipped, not terminate the payload loop: the agent node still emits."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        hook_msg = AIMessage(content="", tool_calls=[{"id": "old", "name": "t", "args": {}}])
        agent_msg = AIMessage(content="", tool_calls=[{"id": "new", "name": "t", "args": {}}])

        events = [
            ((), "updates", {"pre_model_hook": {"messages": [hook_msg]}, "agent": {"messages": [agent_msg]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert results == [
            'data: {"tool_data": {"tool_name": "t", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_non_dict_state_update_with_messages_word(self, mock_sm, mock_format):
        """A non-dict state update containing the word 'messages' must be
        skipped (an `or` in the guard would crash on it)."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        events = [((), "updates", {"agent": "state with messages payload"})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_format.assert_not_awaited()
        assert results == ['nostream: {"complete_message": ""}', "data: [DONE]\n\n"]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_update_msg_without_tool_calls_skipped(self, mock_sm, mock_format):
        """A message lacking the tool_calls attribute is skipped cleanly."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        bare = SimpleNamespace(response_metadata=None)

        events = [((), "updates", {"agent": {"messages": [bare]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_format.assert_not_awaited()
        assert results == ['nostream: {"complete_message": ""}', "data: [DONE]\n\n"]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_msg_without_tool_calls_then_valid_in_same_update(self, mock_sm, mock_format):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        bare = SimpleNamespace(response_metadata=None)
        agent_msg = AIMessage(content="", tool_calls=[{"id": "tc2", "name": "t", "args": {}}])

        events = [((), "updates", {"agent": {"messages": [bare, agent_msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert results == [
            'data: {"tool_data": {"tool_name": "t", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_tool_call_without_id_then_valid(self, mock_sm, mock_format):
        """A tool call without an id is skipped individually — the following
        one still emits a tool_data frame."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        agent_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc1", "name": "t", "args": {}},
            ],
        )
        # An id-less tool call cannot be built through pydantic; append it raw.
        # It must come FIRST so a `break` on it would skip the valid call.
        agent_msg.tool_calls.insert(0, {"name": "no_id", "args": {}})

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_format.assert_awaited_once()
        assert results == [
            'data: {"tool_data": {"tool_name": "t", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_tool_data_deduplicated_across_updates(self, mock_sm, mock_format):
        """The same tool call id in two updates emits exactly one tool_data
        frame."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        agent_msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "t", "args": {}}])

        events = [
            ((), "updates", {"agent": {"messages": [agent_msg]}}),
            ((), "updates", {"agent": {"messages": [agent_msg]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert mock_format.await_count == 1
        assert results == [
            'data: {"tool_data": {"tool_name": "t", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_streaming_handoff_resolution(self, mock_sm, mock_handoff, mock_format):
        """A handoff tool call resolves its metadata and forwards every field
        into the formatted entry."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_handoff.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "github",
            "integration_name": "GitHub",
        }
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        tc = {"id": "tc1", "name": "handoff", "args": {"subagent_id": "github"}}
        agent_msg = AIMessage(content="", tool_calls=[tc])
        expected_tc = agent_msg.tool_calls[0]

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        mock_handoff.assert_awaited_once_with("github")
        mock_format.assert_awaited_once_with(
            expected_tc,
            icon_url="https://icon.png",
            integration_id="github",
            integration_name="GitHub",
            user_id=USER_ID,
        )
        assert results == [
            'data: {"tool_data": {"tool_name": "handoff", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_streaming_handoff_without_subagent_id_skips_lookup(
        self, mock_sm, mock_handoff, mock_format
    ):
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        tc = {"id": "tc1", "name": "handoff", "args": {}}
        agent_msg = AIMessage(content="", tool_calls=[tc])
        expected_tc = agent_msg.tool_calls[0]

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_handoff.assert_not_awaited()
        mock_format.assert_awaited_once_with(
            expected_tc,
            icon_url=None,
            integration_id=None,
            integration_name=None,
            user_id=None,
        )
        assert results == [
            'data: {"tool_data": {"tool_name": "handoff", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_streaming_handoff_without_args_key_skips_lookup(
        self, mock_sm, mock_handoff, mock_format
    ):
        """A handoff tool call with no args dict must not crash: args defaults
        to {}, the lookup is skipped, and the call is still formatted."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "handoff", "data": {}}

        agent_msg = AIMessage(
            content="", tool_calls=[{"id": "tc1", "name": "handoff", "args": {}}]
        )
        # An args-less tool call cannot be built through pydantic; strip it raw.
        del agent_msg.tool_calls[0]["args"]

        events = [((), "updates", {"agent": {"messages": [agent_msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_handoff.assert_not_awaited()
        assert results == [
            'data: {"tool_data": {"tool_name": "handoff", "data": {}}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_fallback_frame_without_model_name(self, mock_sm, mock_format):
        """A fallback flag without gaia_fallback_model reports an empty model
        string, not a substitution default."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        msg = AIMessage(
            content="",
            tool_calls=[],
            response_metadata={"gaia_fell_back": True},
        )

        events = [((), "updates", {"agent": {"messages": [msg]}})]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        assert results == [
            'data: {"model_fallback": {"model": ""}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_updates_then_messages_accumulates(self, mock_sm, mock_format):
        """The updates branch must not terminate the stream: a following
        messages chunk still streams and accumulates."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {"tool_name": "t", "data": {}}

        tool_msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "t", "args": {}}])
        chunk = AIMessageChunk(content="Hello")

        events = [
            ((), "updates", {"agent": {"messages": [tool_msg]}}),
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        assert results == [
            'data: {"tool_data": {"tool_name": "t", "data": {}}}\n\n',
            'data: {"response": "Hello"}\n\n',
            'nostream: {"complete_message": "Hello"}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_todo_tool_message_then_normal_tool_message(self, mock_sm, mock_claim):
        """Todo-tool suppression is per-message: a normal ToolMessage after a
        suppressed one still streams its output."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        todo_msg = ToolMessage(content="plan", tool_call_id="tc1", name="plan_tasks")
        normal_msg = ToolMessage(content="result", tool_call_id="tc2")

        events = [
            ((), "messages", (todo_msg, {"agent_name": "comms_agent"})),
            ((), "messages", (normal_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_claim.assert_called_once_with("", "tc2")
        assert results == [
            'data: {"tool_output": {"tool_call_id": "tc2", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_claim_with_empty_stream_id(self, mock_sm, mock_claim):
        """A run without a stream_id claims with the empty string."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        tool_msg = ToolMessage(content="result", tool_call_id="tc1")

        events = [((), "messages", (tool_msg, {"agent_name": "comms_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"stream_id": None}}
        ):
            results.append(s)

        mock_claim.assert_called_once_with("", "tc1")
        assert results == [
            'data: {"tool_output": {"tool_call_id": "tc1", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_resource_values_win_over_fallbacks(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """csp/permissions returned by the resource override the buffered
        mcp_ui metadata."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {"tool_call_id": "tc_r", "tool_name": "t", "inputs": {}},
            "mcp_ui": {"resource_uri": "/r"},
            "mcp_server_url": "https://mcp.r",
            "timestamp": "t-r",
        }
        mock_fetch.return_value = {"html": "h", "csp": "csp-r", "permissions": ["perm-r"]}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_r", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_r")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_r",
                    "tool_name": "t",
                    "server_url": "https://mcp.r",
                    "resource_uri": "/r",
                    "html_content": "h",
                    "tool_result": "result",
                    "csp": "csp-r",
                    "permissions": ["perm-r"],
                    "tool_arguments": {},
                },
                "timestamp": "t-r",
            }
        }
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_r", "output": "result"}}\n\n',
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_falls_back_to_ui_metadata(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """When the resource omits csp/permissions, the buffered mcp_ui values
        are used."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {"tool_call_id": "tc_f", "tool_name": "t", "inputs": {"q": 1}},
            "mcp_ui": {
                "resource_uri": "/f",
                "csp": "csp-f",
                "permissions": ["perm-f"],
            },
            "mcp_server_url": "https://mcp.f",
            "timestamp": "t-f",
        }
        mock_fetch.return_value = {"html": "h"}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_f", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_f")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_f",
                    "tool_name": "t",
                    "server_url": "https://mcp.f",
                    "resource_uri": "/f",
                    "html_content": "h",
                    "tool_result": "result",
                    "csp": "csp-f",
                    "permissions": ["perm-f"],
                    "tool_arguments": {"q": 1},
                },
                "timestamp": "t-f",
            }
        }
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_f", "output": "result"}}\n\n',
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_minimal_entry_uses_defaults(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """A minimal tool_calls_data entry fills every optional field with its
        documented default ("" / {} / []), and a missing user_id fetches with
        the empty string."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "data": {"tool_call_id": "tc_m"},
            "mcp_ui": {"resource_uri": "/m"},
            "timestamp": "t-m",
        }
        mock_fetch.return_value = {"html": "h"}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_m", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_m")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_fetch.assert_awaited_once_with(
            server_url="",
            resource_uri="/m",
            user_id="",
        )
        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "",
                "data": {
                    "tool_call_id": "tc_m",
                    "tool_name": "",
                    "server_url": "",
                    "resource_uri": "/m",
                    "html_content": "h",
                    "tool_result": "result",
                    "csp": None,
                    "permissions": [],
                    "tool_arguments": {},
                },
                "timestamp": "t-m",
            }
        }
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_m", "output": "result"}}\n\n',
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_entry_without_tool_call_id_not_buffered(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """A tool_calls_data entry with no tool_call_id in its data is never
        buffered — no mcp_app frame follows the tool result."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {},
            "mcp_ui": {"resource_uri": "/x"},
            "mcp_server_url": "https://mcp.x",
            "timestamp": "t-x",
        }
        mock_fetch.return_value = {"html": "h"}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_x", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_x")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_fetch.assert_not_awaited()
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_x", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_mcp_app_fetch_error_logged(self, mock_sm, mock_format, mock_claim, mock_fetch, mock_log):
        """A failing resource fetch is logged loudly and the tool_output frame
        still streams."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "tool_calls_data",
            "tool_category": "mcp",
            "data": {"tool_call_id": "tc_e", "tool_name": "t", "inputs": {}},
            "mcp_ui": {"resource_uri": "/e"},
            "mcp_server_url": "https://mcp.e",
            "timestamp": "t-e",
        }
        mock_fetch.side_effect = Exception("fetch-boom")

        msg = AIMessage(content="", tool_calls=[{"id": "tc_e", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_e")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_log.warning.assert_called_once_with(
            "Failed to emit mcp_app event",
            error="fetch-boom",
            error_type="Exception",
        )
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_e", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.claim_tool_output", return_value=True)
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_non_tool_calls_data_entry_with_ui_not_buffered(
        self, mock_sm, mock_format, mock_claim, mock_fetch
    ):
        """An entry that is not tool_calls_data is never buffered for mcp_app,
        even when it carries mcp_ui + resource_uri."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_format.return_value = {
            "tool_name": "web_search",
            "tool_category": "web",
            "data": {"tool_call_id": "tc_w", "tool_name": "t", "inputs": {}},
            "mcp_ui": {"resource_uri": "/w"},
            "mcp_server_url": "https://mcp.w",
            "timestamp": "t-w",
        }
        mock_fetch.return_value = {"html": "h"}

        msg = AIMessage(content="", tool_calls=[{"id": "tc_w", "name": "t", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc_w")

        events = [
            ((), "updates", {"agent": {"messages": [msg]}}),
            ((), "messages", (tool_msg, {"agent_name": "comms_agent"})),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"agent_name": "comms_agent", "configurable": {}}
        ):
            results.append(s)

        mock_fetch.assert_not_awaited()
        assert results == [
            f"data: {json.dumps({'tool_data': mock_format.return_value})}\n\n",
            'data: {"tool_output": {"tool_call_id": "tc_w", "output": "result"}}\n\n',
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_mcp_app_minimal_entry_uses_defaults(self, mock_sm, mock_fetch):
        """A minimal subagent tool_calls_data custom event fills every optional
        field with its default, and a missing user_id fetches with ''."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "h"}

        calls_event = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "data": {"tool_call_id": "tc_s"},
                "mcp_ui": {"resource_uri": "/s"},
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_s", "output": "r"}}

        events = [
            ((), "custom", calls_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_fetch.assert_awaited_once_with(
            server_url="",
            resource_uri="/s",
            user_id="",
        )
        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "",
                "data": {
                    "tool_call_id": "tc_s",
                    "tool_name": "",
                    "server_url": "",
                    "resource_uri": "/s",
                    "html_content": "h",
                    "tool_result": "r",
                    "csp": None,
                    "permissions": [],
                    "tool_arguments": {},
                },
                "timestamp": None,
            }
        }
        assert results == [
            f"data: {json.dumps(calls_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_entry_without_data_key_not_buffered(self, mock_sm, mock_fetch):
        """A subagent tool_calls_data event without a data dict is skipped
        without crashing, and a later tool_output emits nothing."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "h"}

        no_data_event = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "mcp_ui": {"resource_uri": "/n"},
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_n", "output": "r"}}

        events = [
            ((), "custom", no_data_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_fetch.assert_not_awaited()
        assert results == [
            f"data: {json.dumps(no_data_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_non_tool_calls_data_with_ui_not_buffered(self, mock_sm, mock_fetch):
        """A subagent custom event that is not tool_calls_data is never
        buffered for mcp_app even with mcp_ui + resource_uri."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "h"}

        calls_event = {
            "tool_data": {
                "tool_name": "web_search",
                "data": {"tool_call_id": "tc_w", "tool_name": "t", "inputs": {}},
                "mcp_ui": {"resource_uri": "/w"},
                "mcp_server_url": "https://mcp.w",
                "timestamp": "t-w",
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_w", "output": "r"}}

        events = [
            ((), "custom", calls_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_fetch.assert_not_awaited()
        assert results == [
            f"data: {json.dumps(calls_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_non_dict_tool_data_skipped(self, mock_sm, mock_fetch):
        """A non-dict tool_data custom event is skipped without crashing."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "h"}

        bad_event = {"tool_data": "just a string"}
        output_event = {"tool_output": {"tool_call_id": "tc_x", "output": "r"}}

        events = [
            ((), "custom", bad_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_fetch.assert_not_awaited()
        assert results == [
            f"data: {json.dumps(bad_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_mcp_app_resource_values_win(self, mock_sm, mock_fetch):
        """Subagent mcp_app: resource csp/permissions override the buffered
        mcp_ui metadata."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.return_value = {"html": "h", "csp": "csp-s", "permissions": ["perm-s"]}

        calls_event = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "tool_category": "mcp",
                "data": {"tool_call_id": "tc_r", "tool_name": "t", "inputs": {}},
                "mcp_ui": {"resource_uri": "/r"},
                "mcp_server_url": "https://mcp.r",
                "timestamp": "t-r",
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_r", "output": "r"}}

        events = [
            ((), "custom", calls_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(
            graph, {}, {"configurable": {"user_id": USER_ID}}
        ):
            results.append(s)

        expected_mcp_app = {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "mcp",
                "data": {
                    "tool_call_id": "tc_r",
                    "tool_name": "t",
                    "server_url": "https://mcp.r",
                    "resource_uri": "/r",
                    "html_content": "h",
                    "tool_result": "r",
                    "csp": "csp-s",
                    "permissions": ["perm-s"],
                    "tool_arguments": {},
                },
                "timestamp": "t-r",
            }
        }
        assert results == [
            f"data: {json.dumps(calls_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            f"data: {json.dumps(expected_mcp_app)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.fetch_mcp_ui_resource", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_subagent_mcp_app_fetch_error_logged(self, mock_sm, mock_fetch, mock_log):
        """A failing subagent resource fetch is logged loudly and the stream
        still completes."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)
        mock_fetch.side_effect = Exception("fetch-boom")

        calls_event = {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "data": {"tool_call_id": "tc_e", "tool_name": "t", "inputs": {}},
                "mcp_ui": {"resource_uri": "/e"},
                "mcp_server_url": "https://mcp.e",
                "timestamp": "t-e",
            }
        }
        output_event = {"tool_output": {"tool_call_id": "tc_e", "output": "r"}}

        events = [
            ((), "custom", calls_event),
            ((), "custom", output_event),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = []
        async for s in execute_graph_streaming(graph, {}, {"configurable": {}}):
            results.append(s)

        mock_log.warning.assert_called_once_with(
            "Failed to emit mcp_app from subagent",
            error="fetch-boom",
            error_type="Exception",
        )
        assert results == [
            f"data: {json.dumps(calls_event)}\n\n",
            f"data: {json.dumps(output_event)}\n\n",
            'nostream: {"complete_message": ""}',
            "data: [DONE]\n\n",
        ]


# ---------------------------------------------------------------------------
# Async iterator helper
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item
