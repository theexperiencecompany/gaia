"""Comprehensive tests for app/helpers/agent_helpers.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
import pytest

from app.agents.llm.lane import AgentRole, ModelLane
from app.agents.llm.types import LLMProviderName
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentThread,
    AgentTracing,
    AgentTurn,
    _accumulate_silent_custom_event,
    _collect_silent_tool_entries,
    _hold_silent_chunk,
    _record_interruption_quietly,
    _stamp_langfuse,
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    get_handoff_metadata,
)
from app.models.integration_models import Integration
from app.models.mcp_config import SubAgentConfig
from app.models.payment_models import PlanType
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
    async def test_basic_config(self, mock_providers):
        mock_providers.get.return_value = None  # no posthog

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
        )

        from app.constants.llm import AGENT_RECURSION_LIMIT

        assert config["configurable"]["thread_id"] == CONV_ID
        assert config["configurable"]["user_id"] == USER_ID
        # No stored home zone and no parent zone -> UTC.
        assert config["configurable"]["user_timezone"] == "UTC"
        assert config["recursion_limit"] == AGENT_RECURSION_LIMIT

    @patch("app.helpers.agent_helpers.providers")
    async def test_uses_home_profile_timezone(self, mock_providers):
        """The agent operates in the user's stored home zone (IANA, DST-aware)."""
        mock_providers.get.return_value = None

        home_user = {**FAKE_USER, "timezone": "Asia/Kolkata"}
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=home_user,
                agent_name="comms_agent",
            ),
        )
        assert config["configurable"]["user_timezone"] == "Asia/Kolkata"

    @patch("app.helpers.agent_helpers.providers")
    async def test_inherits_home_timezone_from_base_configurable(self, mock_providers):
        """A child agent reconstructs a bare user dict, so it inherits the home
        zone from the parent's configurable (user_timezone)."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable={"user_timezone": "Asia/Kolkata"},
            ),
        )
        assert config["configurable"]["user_timezone"] == "Asia/Kolkata"

    @patch("app.helpers.agent_helpers.providers")
    async def test_custom_thread_id(self, mock_providers):
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            thread=AgentThread(
                thread_id="custom-thread",
            ),
        )
        assert config["configurable"]["thread_id"] == "custom-thread"

    @patch("app.helpers.agent_helpers.providers")
    async def test_base_configurable_inheritance(self, mock_providers):
        mock_providers.get.return_value = None

        parent_lane = ModelLane(
            provider="gemini",
            model="parent-model",
            reasoning={"effort": "high"},
            provider_pin={"provider": {"only": ["parent-vendor"]}},
            max_input_tokens=128_000,
        )
        base = {
            "lane": parent_lane.to_configurable(),
            "selected_tool": "web_search",
            "vfs_session_id": "vfs-sess-1",
        }

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable=base,
            ),
        )
        configurable = config["configurable"]
        # The lane is inherited WHOLE — one rule, no per-key table. The pin and the
        # reasoning budget were previously governed by two different rules (a
        # conditional copy, and never-inherited-at-all), which is how a subagent
        # silently dropped the first-party pin onto throttled resellers.
        assert ModelLane.from_configurable(configurable["lane"]) == parent_lane
        # ...and re-expanded into LangChain's binding keys, so the two cannot drift.
        assert configurable["provider"] == "gemini"
        assert configurable["model"] == "parent-model"
        assert configurable["reasoning"] == {"effort": "high"}
        assert configurable["model_kwargs"] == {"provider": {"only": ["parent-vendor"]}}
        assert configurable["selected_tool"] == "web_search"
        assert configurable["vfs_session_id"] == "vfs-sess-1"

    @patch("app.helpers.agent_helpers.providers")
    async def test_every_parent_fallback_key_fills_only_its_own_blank(self, mock_providers):
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

        inherited = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable=base,
                ),
            )
        )["configurable"]
        assert {key: inherited[key] for key in base} == base

    @patch("app.helpers.agent_helpers.providers")
    async def test_child_value_wins_over_parent_for_fallback_keys(self, mock_providers):
        """The parent only fills a blank — an explicit child value is never clobbered."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={
                        "selected_tool": "parent-tool",
                        "tool_category": "parent-category",
                        "subagent_id": "parent-subagent",
                        "vfs_session_id": "parent-vfs",
                        "active_todo_id": "parent-todo",
                        "execution_mode": "background",
                        "conversation_source": "telegram",
                    },
                    subagent_id="child-subagent",
                    vfs_session_id="child-vfs",
                ),
                turn=AgentTurn(
                    selected_tool="child-tool",
                    tool_category="child-category",
                    active_todo_id="child-todo",
                    execution_mode="interactive",
                    source="web",
                ),
            )
        )["configurable"]

        assert configurable["selected_tool"] == "child-tool"
        assert configurable["tool_category"] == "child-category"
        assert configurable["subagent_id"] == "child-subagent"
        assert configurable["vfs_session_id"] == "child-vfs"
        assert configurable["active_todo_id"] == "child-todo"
        assert configurable["execution_mode"] == "interactive"
        assert configurable["conversation_source"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    async def test_parent_overrides_child_for_conversation_id_and_user_messages(
        self, mock_providers
    ):
        """The TRUE conversation id and the user's verbatim turns are established
        once by comms; a child passing its own wrapped thread id or an
        agent-authored paraphrase must not overwrite them (the HIL intent judge
        grounds gated calls against the user's own words)."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="github_executor_conv-1",
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={
                        "conversation_id": "conv-1",
                        "user_messages": ["delete the repo"],
                    },
                ),
                turn=AgentTurn(
                    user_messages=["the agent's paraphrase"],
                ),
            )
        )["configurable"]

        assert configurable["conversation_id"] == "conv-1"
        assert configurable["user_messages"] == ["delete the repo"]
        # thread_id still tracks the wrapped graph thread, unlike conversation_id.
        assert configurable["thread_id"] == "github_executor_conv-1"

    @patch("app.helpers.agent_helpers.providers")
    async def test_parent_overrides_child_for_the_verbatim_user_request(self, mock_providers):
        """Same rule as ``user_messages``, and for the same reason: comms establishes
        the user's raw words once, and a child agent only ever has its parent's
        paraphrase to offer. ``call_executor`` reads this to build the executor brief,
        so a child winning here would put the paraphrase back where the verbatim copy
        belongs — the exact failure this key exists to prevent."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="github_executor_conv-1",
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={
                        "conversation_id": "conv-1",
                        "user_request": "delete the repo",
                    },
                ),
                turn=AgentTurn(
                    user_request="the agent's paraphrase",
                ),
            )
        )["configurable"]

        assert configurable["user_request"] == "delete the repo"

    @patch("app.helpers.agent_helpers.providers")
    async def test_a_root_run_carries_its_own_verbatim_request(self, mock_providers):
        """With no parent there is nothing to inherit, so the value passed in is the
        one that lands — this is the comms root, where the raw message enters."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="conv-1",
                    user=FAKE_USER,
                    agent_name="comms_agent",
                ),
                turn=AgentTurn(
                    user_request="pls archive the junk mail",
                ),
            )
        )["configurable"]

        assert configurable["user_request"] == "pls archive the junk mail"

    @patch("app.helpers.agent_helpers.providers")
    async def test_a_handoff_subagent_inherits_preferences_established_by_comms(
        self, mock_providers
    ) -> None:
        """``user_preferences`` / ``writing_style`` follow the exact same rule as
        ``user_messages`` above: established once wherever the root call site has
        the full user document (comms), a child agent (executor, a handoff
        subagent) never has its own copy to prefer, so the parent's value wins."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="conv-1",
                    user=FAKE_USER,
                    agent_name="gmail_agent",
                ),
                thread=AgentThread(
                    base_configurable={
                        "conversation_id": "conv-1",
                        "user_preferences": {"profession": "engineer"},
                        "writing_style": {"summary": "terse"},
                    },
                ),
            )
        )["configurable"]

        assert configurable["user_preferences"] == {"profession": "engineer"}
        assert configurable["writing_style"] == {"summary": "terse"}

    @patch("app.helpers.agent_helpers.providers")
    async def test_no_parent_and_no_explicit_value_leaves_preferences_absent(
        self, mock_providers
    ) -> None:
        """A root call site with no onboarding data (e.g. a dev user who hasn't
        onboarded) must not fabricate a value — the context section reads a
        missing key as "render nothing", never as a stale default."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="conv-1",
                    user=FAKE_USER,
                    agent_name="executor_agent",
                ),
            )
        )["configurable"]

        assert configurable["user_preferences"] is None
        assert configurable["writing_style"] is None

    @patch("app.helpers.agent_helpers.providers")
    async def test_session_id_is_the_conversation_when_there_is_no_parent(self, mock_providers):
        """The sticky-routing key defaults to the conversation id itself."""
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="comms_agent",
                ),
            )
        )["configurable"]

        assert configurable["session_id"] == CONV_ID

    @patch("app.helpers.agent_helpers.providers")
    async def test_session_id_is_inherited_verbatim_from_the_parent(self, mock_providers):
        """Every agent in the tree routes on the parent's sticky key, not its own id.

        A child is spawned with a wrapped thread id as its ``conversation_id``, so
        deriving the key locally would send it to a provider with a cold cache.
        """
        mock_providers.get.return_value = None

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="github_executor_conv-1",
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={"session_id": "conv-1"},
                ),
            )
        )["configurable"]

        assert configurable["session_id"] == "conv-1"

    @patch("app.helpers.agent_helpers.providers")
    async def test_session_id_survives_a_parent_that_carries_none(self, mock_providers):
        """A parent that explicitly holds no sticky key hands down that absence.

        Present-but-None and absent are different: the key is inherited on
        presence, so a parent routing without one must not have a child invent one.
        """
        mock_providers.get.return_value = None

        with_none = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={"session_id": None},
                ),
            )
        )["configurable"]
        without_key = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={"selected_tool": "web_search"},
                ),
            )
        )["configurable"]

        assert with_none["session_id"] is None
        assert without_key["session_id"] == CONV_ID

    @patch("app.helpers.agent_helpers.providers")
    async def test_stream_id_always_comes_from_the_parent(self, mock_providers):
        """Pass-through, not a fallback: a child never invents its own stream."""
        mock_providers.get.return_value = None

        with_parent = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={"stream_id": "stream-9"},
                ),
            )
        )["configurable"]
        without_parent = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="comms_agent",
                ),
            )
        )["configurable"]

        assert with_parent["stream_id"] == "stream-9"
        assert without_parent["stream_id"] is None

    @patch("app.helpers.agent_helpers.providers")
    async def test_workflow_context_survives_into_a_child_agents_config(self, mock_providers):
        """A workflow fire stamps its workflow on the comms configurable; the
        executor and its handoff subagents must see the same workflow, or the
        playbook tools inside the run refuse with "not in a workflow run"."""
        mock_providers.get.return_value = None

        child = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="executor",
                ),
                thread=AgentThread(
                    base_configurable={
                        "workflow_id": "wf_123",
                        "workflow_title": "Inbox Triage",
                        "workflow_notify_on_completion": False,
                    },
                ),
            )
        )["configurable"]
        top_level = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID,
                    user=FAKE_USER,
                    agent_name="comms_agent",
                ),
            )
        )["configurable"]

        assert child["workflow_id"] == "wf_123"
        assert child["workflow_title"] == "Inbox Triage"
        assert child["workflow_notify_on_completion"] is False
        assert "workflow_id" not in top_level

    @patch("app.helpers.agent_helpers.providers")
    async def test_posthog_callback_added(self, mock_providers):
        mock_providers.get.return_value = MagicMock()  # posthog client present

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
        )
        assert len(config["callbacks"]) >= 1

    @patch("app.helpers.agent_helpers.providers")
    async def test_usage_metadata_callback(self, mock_providers):
        mock_providers.get.return_value = None

        usage_cb = MagicMock()
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            tracing=AgentTracing(
                usage_metadata_callback=usage_cb,
            ),
        )
        assert usage_cb in config["callbacks"]

    @patch("app.helpers.agent_helpers.providers")
    async def test_selected_tool_and_category(self, mock_providers):
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            turn=AgentTurn(
                selected_tool="search",
                tool_category="web",
            ),
        )
        assert config["configurable"]["selected_tool"] == "search"
        assert config["configurable"]["tool_category"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    async def test_bot_source_sets_bot_category_and_channel(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            turn=AgentTurn(
                source="whatsapp",
            ),
        )
        # raw channel preserved in configurable; generalized category derived
        assert config["configurable"]["conversation_source"] == "whatsapp"
        assert config["configurable"]["source_category"] == "bot"
        # both surfaced on trace metadata for observability
        assert config["metadata"]["source_category"] == "bot"
        assert config["metadata"]["source_channel"] == "whatsapp"

    @patch("app.helpers.agent_helpers.providers")
    async def test_web_source_sets_ui_category(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            turn=AgentTurn(
                source="web",
            ),
        )
        assert config["configurable"]["source_category"] == "ui"
        assert config["metadata"]["source_category"] == "ui"
        assert config["metadata"]["source_channel"] == "web"

    @patch("app.helpers.agent_helpers.providers")
    async def test_missing_source_defaults_to_background(self, mock_providers) -> None:
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
        )
        # no source -> BG category, channel labelled "background" in metadata
        assert config["configurable"]["conversation_source"] is None
        assert config["configurable"]["source_category"] == "bg"
        assert config["metadata"]["source_category"] == "bg"
        assert config["metadata"]["source_channel"] == "background"

    @patch("app.helpers.agent_helpers.providers")
    async def test_source_inherited_from_base_configurable(self, mock_providers) -> None:
        """A child agent (e.g. executor) inherits the channel from its parent and
        recomputes the category — so background runs are still tagged Bot/UI."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable={"conversation_source": "telegram"},
            ),
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
        chunk1 = AIMessageChunk(content="Hello ", id="msg-1")
        chunk2 = AIMessageChunk(content="world", id="msg-1")

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
        chunk = AIMessageChunk(content="should be skipped", id="msg-1")

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
        chunk = AIMessageChunk(content="executor text", id="msg-1")

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
        """tool_data entries ACCUMULATE across events while every other key is
        merged by name — a second event's tool_data must not replace the first
        event's entries."""
        mock_process.side_effect = [
            {"tool_data": [{"tool_name": "first_tool"}]},
            {
                "tool_data": [{"tool_name": "custom_tool"}],
                "follow_up_actions": ["action1"],
            },
        ]

        events = [
            ((), "custom", {"some": "data"}),
            ((), "custom", {"other": "data"}),
        ]

        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        _, tool_data = await execute_graph_silent(
            graph,
            {},
            {"configurable": {"user_id": USER_ID}},
        )
        assert [e["tool_name"] for e in tool_data["tool_data"]] == [
            "first_tool",
            "custom_tool",
        ]
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

    async def test_a_handoff_preamble_is_never_persisted(self):
        """Text that turns out to accompany a tool call is narration, not a
        reply. The silent driver holds it by message id and drops it when the
        node's own boundary reveals the handoff — the same rule the streaming
        driver enforces, on the path workflows and background runs take."""
        preamble = AIMessageChunk(content="let me get that set up", id="msg-1")
        handoff = AIMessage(
            content="let me get that set up",
            id="msg-1",
            tool_calls=[{"id": "tc_1", "name": "call_executor", "args": {"task": "x"}}],
        )

        events = [
            ((), "messages", (preamble, {"agent_name": "comms_agent"})),
            ((), "updates", {"agent": {"messages": [handoff]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "tool_calls_data", "data": {}},
        ):
            msg, tool_data = await execute_graph_silent(
                graph,
                {},
                {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}},
            )

        assert msg == ""
        # ...and silencing the narration did not silence the tool card.
        assert len(tool_data["tool_data"]) == 1

    async def test_a_tool_free_reply_survives_its_boundary(self):
        """The other half of the same rule: a message that ends without a tool
        call is the answer, and the boundary must release it."""
        chunk = AIMessageChunk(content="all set up now.", id="msg-1")
        reply = AIMessage(content="all set up now.", id="msg-1")

        events = [
            ((), "messages", (chunk, {"agent_name": "comms_agent"})),
            ((), "updates", {"agent": {"messages": [reply]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"agent_name": "comms_agent", "configurable": {"user_id": USER_ID}},
        )

        assert msg == "all set up now."

    async def test_a_non_comms_run_never_inspects_boundaries(self):
        """The executor's text is read by comms, never by a person, so it is
        never accumulated and its boundaries decide nothing."""
        chunk = AIMessageChunk(content="executor text", id="msg-1")
        reply = AIMessage(content="executor text", id="msg-1")

        events = [
            ((), "messages", (chunk, {"agent_name": "executor_agent"})),
            ((), "updates", {"agent": {"messages": [reply]}}),
        ]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        msg, _ = await execute_graph_silent(
            graph,
            {},
            {"agent_name": "executor_agent", "configurable": {"user_id": USER_ID}},
        )

        assert msg == ""


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
    async def test_a_run_that_was_never_cancelled_says_so_by_omission(self, mock_sm):
        """The endpoint keys the cancel path off this marker. A run that always
        reported itself cancelled would close every stream through the
        interruption path — recording an interruption that never happened and
        acking a cancel nobody asked for."""
        mock_sm.is_cancelled = AsyncMock(return_value=False)

        chunk = AIMessageChunk(content="done.", id="msg-1")
        events = [((), "messages", (chunk, {"agent_name": "comms_agent"}))]
        graph = AsyncMock()
        graph.astream = MagicMock(return_value=_async_iter(events))

        results = [
            frame
            async for frame in execute_graph_streaming(
                graph, {}, {"agent_name": "comms_agent", "configurable": {"stream_id": "s1"}}
            )
        ]

        marker = next(r for r in results if r.startswith("nostream: "))
        assert json.loads(marker.removeprefix("nostream: ")) == {"complete_message": "done."}

    @patch("app.helpers.agent_helpers.stream_manager")
    async def test_cancellation(self, mock_sm):
        mock_sm.is_cancelled = AsyncMock(return_value=True)

        chunk = AIMessageChunk(content="text", id="msg-1")

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

        chunk = AIMessageChunk(content="Hello", id="msg-1")

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
# _stamp_langfuse
# ---------------------------------------------------------------------------


class TestStampLangfuse:
    """The exact keys the Langfuse SDK reads. Every one of them is a string
    literal the SDK matches by name, so a renamed or blanked key does not fail
    anywhere in GAIA — the trace just silently loses that dimension. Pinning the
    WHOLE dict (not key-by-key membership) is what makes a rename visible."""

    def test_a_traced_run_stamps_every_langfuse_key_by_name(self):
        configurable = {}
        metadata = {}

        _stamp_langfuse(
            configurable,
            metadata,
            "trace-abc",
            ["tag-one"],
            {"user_id": USER_ID},
            CONV_ID,
        )

        assert configurable == {
            "langfuse_trace_id": "trace-abc",
            "langfuse_tags": ["tag-one"],
        }
        assert metadata == {
            "langfuse_trace_id": "trace-abc",
            # The session is the CONVERSATION, not the thread: Langfuse groups a
            # whole chat under it.
            "langfuse_session_id": CONV_ID,
            "langfuse_user_id": USER_ID,
            "langfuse_tags": ["tag-one"],
        }

    def test_an_untraced_run_stamps_nothing_at_all(self):
        """No trace id means no Langfuse binding anywhere — not even the tags,
        which are meaningless without a trace to hang them on."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, None, None, {"user_id": USER_ID}, CONV_ID)

        assert configurable == {}
        assert metadata == {}

    def test_tags_reach_the_configurable_even_without_a_trace_id(self):
        """The configurable's tags are stamped from their OWN guard, so a child
        agent still inherits them when this run has no trace of its own."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, None, ["tag-one"], {"user_id": USER_ID}, CONV_ID)

        assert configurable == {"langfuse_tags": ["tag-one"]}
        assert metadata == {}

    def test_an_anonymous_user_leaves_the_user_dimension_off(self):
        """A background run has no user id; Langfuse must get no user key at all
        rather than a null one."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, "trace-abc", None, {}, CONV_ID)

        assert metadata == {
            "langfuse_trace_id": "trace-abc",
            "langfuse_session_id": CONV_ID,
        }


# ---------------------------------------------------------------------------
# build_agent_config: callbacks, lane resolution, Langfuse and workflow wiring
# ---------------------------------------------------------------------------


DEV_LANE = ModelLane(
    provider=LLMProviderName.OPENROUTER,
    model="dev/model",
    reasoning=None,
    provider_pin=None,
    max_input_tokens=64_000,
)

DEV_OPTION = {
    "provider": LLMProviderName.OPENROUTER,
    "model": "dev/model",
    "model_kwargs": None,
    "reasoning": False,
}


class TestBuildAgentConfigCallbackWiring:
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers._build_agent_callbacks")
    async def test_the_callbacks_are_built_for_this_conversation_and_this_agent(
        self, mock_build_callbacks, mock_resolve
    ):
        """PostHog attributes the run's LLM spans from these two values alone, so
        a dropped conversation id or agent name lands every run in one anonymous
        bucket — visible nowhere but the analytics."""
        mock_resolve.return_value = (DEV_LANE, None)
        mock_build_callbacks.return_value = []
        usage_cb = MagicMock()

        await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            tracing=AgentTracing(usage_metadata_callback=usage_cb),
        )

        assert mock_build_callbacks.call_args.args == (
            CONV_ID,
            FAKE_USER,
            "comms_agent",
            usage_cb,
        )


class TestBuildAgentConfigLaneResolution:
    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_top_level_run_resolves_its_lane_from_user_role_and_dev_pick(
        self, mock_resolve, mock_providers
    ):
        """resolve_lane is the single place a model is chosen; all three inputs
        decide which one. A dropped user id resolves the wrong plan tier, a
        dropped role the wrong reasoning budget, a dropped dev option ignores
        the model switcher entirely."""
        mock_providers.get.return_value = None
        mock_resolve.return_value = (DEV_LANE, PlanType.PRO)

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            lane=AgentLane(role=AgentRole.COMMS, dev_option=DEV_OPTION),
        )

        mock_resolve.assert_awaited_once_with(USER_ID, AgentRole.COMMS, DEV_OPTION)
        assert config["configurable"]["lane"] == DEV_LANE.to_configurable()
        # The plan tier the lane was resolved from rides along for the budget wall.
        assert config["configurable"]["plan_type"] == "pro"

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_child_run_inherits_the_parent_lane_without_resolving(
        self, mock_resolve, mock_providers
    ):
        """Inheritance beats resolving fresh: a child that re-resolves can land
        on a different model mid-conversation."""
        mock_providers.get.return_value = None
        mock_resolve.return_value = (DEV_LANE, None)
        parent_lane = ModelLane(
            provider=LLMProviderName.GEMINI,
            model="parent-model",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=128_000,
        )

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(base_configurable={"lane": parent_lane.to_configurable()}),
        )

        mock_resolve.assert_not_awaited()
        assert config["configurable"]["lane"] == parent_lane.to_configurable()

    @patch("app.helpers.agent_helpers.providers")
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_dev_model_pick_beats_an_inherited_lane(self, mock_resolve, mock_providers):
        """The switcher's whole purpose: an explicit dev choice outranks the
        parent's lane, so the run resolves rather than inherits."""
        mock_providers.get.return_value = None
        mock_resolve.return_value = (DEV_LANE, None)
        parent_lane = ModelLane(
            provider=LLMProviderName.GEMINI,
            model="parent-model",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=128_000,
        )

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            lane=AgentLane(role=AgentRole.SUBAGENT, dev_option=DEV_OPTION),
            thread=AgentThread(base_configurable={"lane": parent_lane.to_configurable()}),
        )

        mock_resolve.assert_awaited_once_with(USER_ID, AgentRole.SUBAGENT, DEV_OPTION)
        assert config["configurable"]["lane"] == DEV_LANE.to_configurable()


class TestBuildAgentConfigLangfuseWiring:
    @patch("app.helpers.agent_helpers.providers")
    async def test_the_stamp_names_this_conversation_and_this_user(self, mock_providers):
        """Everything the trace is bound to comes from this one call: the trace,
        the session (the conversation), the user and the tags."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
            tracing=AgentTracing(langfuse_trace_id="trace-abc", langfuse_tags=["tag-one"]),
        )

        assert config["configurable"]["langfuse_trace_id"] == "trace-abc"
        assert config["configurable"]["langfuse_tags"] == ["tag-one"]
        assert config["metadata"]["langfuse_trace_id"] == "trace-abc"
        assert config["metadata"]["langfuse_session_id"] == CONV_ID
        assert config["metadata"]["langfuse_user_id"] == USER_ID
        assert config["metadata"]["langfuse_tags"] == ["tag-one"]

    @patch("app.helpers.agent_helpers.providers")
    async def test_a_child_lands_on_the_parents_trace_and_tags(self, mock_providers):
        """A child agent passes no tracing of its own, so the executor's spans
        have to join the comms trace rather than starting a second one."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable={
                    "langfuse_trace_id": "parent-trace",
                    "langfuse_tags": ["parent-tag"],
                }
            ),
        )

        assert config["configurable"]["langfuse_trace_id"] == "parent-trace"
        assert config["configurable"]["langfuse_tags"] == ["parent-tag"]
        assert config["metadata"]["langfuse_trace_id"] == "parent-trace"

    @patch("app.helpers.agent_helpers.providers")
    async def test_explicit_tracing_beats_what_the_parent_carried(self, mock_providers):
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable={
                    "langfuse_trace_id": "parent-trace",
                    "langfuse_tags": ["parent-tag"],
                }
            ),
            tracing=AgentTracing(langfuse_trace_id="own-trace", langfuse_tags=["own-tag"]),
        )

        assert config["configurable"]["langfuse_trace_id"] == "own-trace"
        assert config["configurable"]["langfuse_tags"] == ["own-tag"]

    @patch("app.helpers.agent_helpers.providers")
    async def test_an_empty_tag_list_clears_the_parents_tags(self, mock_providers):
        """The precedence test is ``is not None``, not truthiness, precisely so a
        caller can pass [] to mean "no tags" instead of "inherit"."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(
                base_configurable={
                    "langfuse_trace_id": "parent-trace",
                    "langfuse_tags": ["parent-tag"],
                }
            ),
            tracing=AgentTracing(langfuse_tags=[]),
        )

        assert "langfuse_tags" not in config["configurable"]
        assert "langfuse_tags" not in config["metadata"]


class TestBuildAgentConfigWorkflowInheritance:
    @patch("app.helpers.agent_helpers.providers")
    async def test_a_workflow_without_a_title_inherits_the_documented_defaults(
        self, mock_providers
    ):
        """A workflow fire that carried no title and no notify preference must
        still produce a titled-by-empty-string, notify-by-default config: the
        playbook tools read both keys unconditionally."""
        mock_providers.get.return_value = None

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor",
            ),
            thread=AgentThread(base_configurable={"workflow_id": "wf_123"}),
        )

        configurable = config["configurable"]
        assert configurable["workflow_id"] == "wf_123"
        assert configurable["workflow_title"] == ""
        assert configurable["workflow_notify_on_completion"] is True


# ---------------------------------------------------------------------------
# _collect_silent_tool_entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCollectSilentToolEntries:
    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_a_message_without_tool_calls_never_stops_the_scan(self, mock_format):
        """A node update carries the user's own turn alongside the model's, and
        only the model's has ``tool_calls``. Skipping is per message: stopping at
        the first one drops every tool card after it."""
        mock_format.return_value = {"tool_name": "custom_tool"}
        ai = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "custom_tool", "args": {}, "type": "tool_call"}],
        )
        entries: list = []
        emitted: set[str] = set()

        await _collect_silent_tool_entries(
            [HumanMessage(content="do the thing"), ai], emitted, entries, USER_ID
        )

        assert entries == [{"tool_name": "custom_tool"}]
        assert emitted == {"tc1"}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_an_unusable_tool_call_is_skipped_and_the_rest_still_emit(self, mock_format):
        """An id-less call and an already-emitted one are both skipped, and the
        scan continues: a break here loses every later call in the same message."""
        mock_format.return_value = {"tool_name": "custom_tool"}
        msg = MagicMock()
        msg.tool_calls = [
            {"id": "", "name": "nameless", "args": {}},
            {"id": "tc_seen", "name": "already_sent", "args": {}},
            {"id": "tc_new", "name": "custom_tool", "args": {}},
        ]
        entries: list = []
        emitted = {"tc_seen"}

        await _collect_silent_tool_entries([msg], emitted, entries, USER_ID)

        assert entries == [{"tool_name": "custom_tool"}]
        assert emitted == {"tc_seen", "tc_new"}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    async def test_a_todo_tool_call_is_skipped_without_ending_the_scan(self, mock_format):
        """Todo tools already stream todo_progress, so their cards are noise —
        but the calls that follow them in the same message are not."""
        mock_format.return_value = {"tool_name": "custom_tool"}
        msg = MagicMock()
        msg.tool_calls = [
            {"id": "tc_plan", "name": "plan_tasks", "args": {}},
            {"id": "tc_real", "name": "custom_tool", "args": {}},
        ]
        entries: list = []
        emitted: set[str] = set()

        await _collect_silent_tool_entries([msg], emitted, entries, USER_ID)

        assert entries == [{"tool_name": "custom_tool"}]
        assert emitted == {"tc_real"}

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_a_handoff_with_no_named_subagent_resolves_no_metadata(
        self, mock_handoff, mock_format
    ):
        """A half-assembled handoff carries no args, or empty ones. Both mean
        "no subagent named yet", and neither may reach the registry."""
        mock_format.return_value = {"tool_name": "handoff"}
        no_args = MagicMock()
        no_args.tool_calls = [{"id": "tc_a", "name": "handoff"}]
        empty_args = MagicMock()
        empty_args.tool_calls = [{"id": "tc_b", "name": "handoff", "args": {}}]
        entries: list = []

        await _collect_silent_tool_entries([no_args, empty_args], set(), entries, USER_ID)

        mock_handoff.assert_not_awaited()
        assert len(entries) == 2

    @patch("app.helpers.agent_helpers.format_tool_call_entry", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers.get_handoff_metadata", new_callable=AsyncMock)
    async def test_handoff_metadata_reaches_the_formatter_field_by_field(
        self, mock_handoff, mock_format
    ):
        """Each display field is forwarded under its own name. A crossed or
        dropped one type-checks fine (all three are ``str | None``) and shows up
        only as a subagent card with the wrong icon or no integration."""
        mock_handoff.return_value = {
            "icon_url": "https://icon.png",
            "integration_id": "github",
            "integration_name": "GitHub",
        }
        mock_format.return_value = {"tool_name": "handoff"}
        tool_call = {"id": "tc_h", "name": "handoff", "args": {"subagent_id": "github"}}
        msg = MagicMock()
        msg.tool_calls = [tool_call]

        await _collect_silent_tool_entries([msg], set(), [], USER_ID)

        mock_handoff.assert_awaited_once_with("github")
        assert mock_format.await_args.args == (tool_call,)
        assert mock_format.await_args.kwargs == {
            "icon_url": "https://icon.png",
            "integration_id": "github",
            "integration_name": "GitHub",
            "user_id": USER_ID,
        }


# ---------------------------------------------------------------------------
# _accumulate_silent_custom_event
# ---------------------------------------------------------------------------


class TestAccumulateSilentCustomEvent:
    @patch("app.helpers.agent_helpers.process_custom_event_for_tools", return_value=None)
    def test_a_todo_snapshot_is_filed_under_its_own_source(self, _mock_process):
        """The accumulator is keyed by source so the planner's and the executor's
        snapshots do not overwrite each other."""
        accumulated: dict = {}

        _accumulate_silent_custom_event(
            {"todo_progress": {"source": "planner", "count": 1}},
            {},
            accumulated,
            {"tool_data": []},
        )

        assert accumulated == {"planner": {"source": "planner", "count": 1}}

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools", return_value=None)
    def test_a_sourceless_todo_snapshot_is_filed_under_the_executor(self, _mock_process):
        """The executor is the emitter that predates the source field, so an
        unlabelled snapshot is its."""
        accumulated: dict = {}

        _accumulate_silent_custom_event(
            {"todo_progress": {"count": 1}}, {}, accumulated, {"tool_data": []}
        )

        assert accumulated == {"executor": {"count": 1}}

    @patch("app.helpers.agent_helpers.process_custom_event_for_tools")
    def test_the_event_payload_itself_is_handed_to_the_tool_parser(self, mock_process):
        mock_process.return_value = {"tool_data": [{"tool_name": "t"}], "follow_up_actions": ["a"]}
        payload = {"some": "custom event"}
        tool_data: dict = {"tool_data": []}

        _accumulate_silent_custom_event(payload, {}, {}, tool_data)

        assert mock_process.call_args.args == (payload,)
        assert tool_data == {"tool_data": [{"tool_name": "t"}], "follow_up_actions": ["a"]}


# ---------------------------------------------------------------------------
# _hold_silent_chunk
# ---------------------------------------------------------------------------


class TestHoldSilentChunk:
    def test_only_the_models_own_chunks_are_held(self):
        """The "messages" stream carries every message type; only an AI chunk is
        a reply-in-progress. Both halves of the guard matter — a present chunk
        that is not the model's must hold nothing."""
        message_texts: dict[str, str] = {}

        _hold_silent_chunk(
            (HumanMessage(content="typed by the user", id="h1"), {}),
            True,
            set(),
            message_texts,
        )

        assert message_texts == {}

    def test_an_ai_chunk_is_held_under_its_message_id(self):
        message_texts: dict[str, str] = {}

        _hold_silent_chunk(
            (AIMessageChunk(content="half ", id="m1"), {}), True, set(), message_texts
        )
        _hold_silent_chunk(
            (AIMessageChunk(content="a reply", id="m1"), {}), True, set(), message_texts
        )

        assert message_texts == {"m1": "half a reply"}

    def test_a_chunk_marked_silent_is_dropped(self):
        """Follow-up-action generation rides the same stream and must never land
        in the user-visible reply."""
        message_texts: dict[str, str] = {}

        _hold_silent_chunk(
            (AIMessageChunk(content="internal", id="m1"), {"silent": True}),
            True,
            set(),
            message_texts,
        )

        assert message_texts == {}


# ---------------------------------------------------------------------------
# _record_interruption_quietly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordInterruptionQuietly:
    @patch("app.helpers.agent_helpers.record_interruption", new_callable=AsyncMock)
    async def test_the_interruption_is_recorded_against_this_run(self, mock_record):
        """Both the graph and its config identify WHICH run was interrupted; a
        recording against the wrong one, or against nothing, is a lost cancel."""
        graph, config = MagicMock(), {"configurable": {"thread_id": CONV_ID}}

        await _record_interruption_quietly(graph, config)

        mock_record.assert_awaited_once_with(graph, config)

    @patch("app.helpers.agent_helpers.log")
    @patch("app.helpers.agent_helpers.record_interruption", new_callable=AsyncMock)
    async def test_a_failed_recording_is_swallowed_and_reported_in_full(
        self, mock_record, mock_log
    ):
        """The cancel ack must still reach the client, so the failure is logged
        rather than raised — which makes the log the ONLY evidence it happened.
        The error text and its type both have to be the real ones."""
        mock_record.side_effect = ValueError("checkpointer down")

        await _record_interruption_quietly(MagicMock(), {})

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args == (f"{LogTag.AGENT} Failed to record interruption",)
        assert mock_log.error.call_args.kwargs == {
            "error": "checkpointer down",
            "error_type": "ValueError",
        }


# ---------------------------------------------------------------------------
# Async iterator helper
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item
