"""Comprehensive tests for app/helpers/agent_helpers.py."""

from collections.abc import Iterator
import inspect
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.agents.llm.lane import AgentRole, ModelLane
from app.agents.llm.ttft import LLMTtftCallback
from app.constants.llm import LLM_LABEL_METADATA_KEY, LLMProviderName
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentThread,
    AgentTracing,
    AgentTurn,
    _build_agent_callbacks,
    _stamp_langfuse,
    background_authorization,
    build_agent_config,
)
from app.models.agent_models import AgentUserContext, run_analytics_context
from app.models.payment_models import PlanType
from app.models.presence_models import PresenceSnapshot
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext, analytics_context, worker_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = "507f1f77bcf86cd799439011"
_TODO_A = {"id": "t1", "content": "draft", "status": "in_progress"}
_TODO_B = {"id": "t1", "content": "draft", "status": "completed"}
CONV_ID = "conv-001"


@pytest.fixture(autouse=True)
def _no_real_presence_read() -> Iterator[AsyncMock]:
    """Keep a root run from reading presence off Redis unless a test patches it itself."""
    with patch("app.helpers.agent_helpers.read_presence", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = {"captured_at": 0, "last_seen": {}}
        yield mock_read


FAKE_USER: AgentUserContext = {
    "user_id": USER_ID,
    "email": "test@example.com",
    "name": "Test User",
}


# ---------------------------------------------------------------------------
# build_agent_config
# ---------------------------------------------------------------------------


class TestBuildAgentConfig:
    async def test_basic_config(self):
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

    async def test_metadata_stamps_the_agent_label_for_the_ttft_callback(self):
        """build_agent_config stamps the agent tier as the default LLM_LABEL_METADATA_KEY, or the graph's own streaming calls land on agent=unknown."""

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="executor_agent",
            ),
        )
        assert config["metadata"][LLM_LABEL_METADATA_KEY] == "executor_agent"

    @pytest.mark.regression
    @pytest.mark.parametrize(("thread_id", "stamped"), [(None, CONV_ID), ("spawn_x", "spawn_x")])
    async def test_metadata_stamps_the_runs_own_thread_on_every_chunk(
        self, thread_id: str | None, stamped: str
    ):
        """Regression: a spawned subagent's chunks, unstamped, became its parent run's answer."""
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor_agent"
            ),
            thread=AgentThread(thread_id=thread_id),
        )

        assert config["metadata"]["agent_thread_id"] == stamped
        assert config["configurable"]["thread_id"] == stamped

    async def test_a_root_run_stamps_the_users_identity_and_its_own_conversation(self):
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=FAKE_USER,
                agent_name="comms_agent",
            ),
        )

        configurable = config["configurable"]
        assert configurable["conversation_id"] == CONV_ID
        assert configurable["email"] == "test@example.com"
        assert configurable["user_name"] == "Test User"
        assert configurable["execution_mode"] == "interactive"
        assert config["metadata"]["user_id"] == USER_ID

    async def test_a_root_run_mints_a_request_id_that_a_child_inherits(self):
        root = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent"
                ),
            )
        )["configurable"]
        child = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"
                ),
                thread=AgentThread(base_configurable={"root_request_id": "root-req-1"}),
            )
        )["configurable"]

        assert str(UUID(root["root_request_id"])) == root["root_request_id"]
        assert child["root_request_id"] == "root-req-1"

    async def test_a_run_tree_acts_as_the_agent_in_the_context_that_started_it(self):
        """Stamped at the root and inherited whole, so a run resumed by a cron keeps the user's turn."""
        users_turn = AnalyticsContext(
            attribution=Attribution(
                actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.BOT
            ),
            posthog_session_id="sess-1",
        )
        with analytics_context(users_turn):
            root = (
                await build_agent_config(
                    identity=AgentIdentity(
                        conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent"
                    ),
                )
            )["configurable"]
        with analytics_context(worker_context(Trigger.SYSTEM)):
            resumed = (
                await build_agent_config(
                    identity=AgentIdentity(
                        conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"
                    ),
                    thread=AgentThread(base_configurable=root),
                )
            )["configurable"]

        expected = users_turn.acting_as(Actor.AGENT)
        assert run_analytics_context(root) == expected
        assert run_analytics_context(resumed) == expected
        # Stored as plain JSON: the configurable is checkpointed and queued past this process.
        assert root["analytics_context"] == {
            "attribution": {"actor": "agent", "trigger": "interactive", "surface": "bot"},
            "posthog_session_id": "sess-1",
        }
        assert type(root["analytics_context"]["attribution"]["actor"]) is str

    async def test_a_child_whose_parent_has_no_zone_falls_back_to_utc(self):
        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"
                ),
                thread=AgentThread(base_configurable={"stream_id": "stream-1"}),
            )
        )["configurable"]

        assert configurable["user_timezone"] == "UTC"

    async def test_uses_home_profile_timezone(self):
        """The agent operates in the user's stored home zone (IANA, DST-aware)."""

        home_user = {**FAKE_USER, "timezone": "Asia/Kolkata"}
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID,
                user=home_user,
                agent_name="comms_agent",
            ),
        )
        assert config["configurable"]["user_timezone"] == "Asia/Kolkata"

    async def test_inherits_home_timezone_from_base_configurable(self):
        """A child agent reconstructs a bare user dict, inheriting the home zone from the parent's configurable."""

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

    async def test_custom_thread_id(self):
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

    async def test_base_configurable_inheritance(self):
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
        # The lane is inherited WHOLE, not per-key — separate copy/inherit rules
        # previously let a subagent silently drop the first-party pin onto
        # throttled resellers.
        assert ModelLane.from_configurable(configurable["lane"]) == parent_lane
        # ...and re-expanded into LangChain's binding keys, so the two cannot drift.
        assert configurable["provider"] == "gemini"
        assert configurable["model"] == "parent-model"
        assert configurable["reasoning"] == {"effort": "high"}
        assert configurable["model_kwargs"] == {"provider": {"only": ["parent-vendor"]}}
        assert configurable["selected_tool"] == "web_search"
        assert configurable["vfs_session_id"] == "vfs-sess-1"

    @patch("app.helpers.agent_helpers.resolve_lane")
    async def test_a_comms_run_keeps_the_comms_lane_it_inherits(self, mock_resolve):
        comms_lane = ModelLane(
            provider=LLMProviderName.OPENAI,
            model="comms-model",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=128_000,
        )

        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent"
            ),
            thread=AgentThread(base_configurable={"lane": comms_lane.to_configurable()}),
            lane=AgentLane(role=AgentRole.COMMS),
        )

        assert ModelLane.from_configurable(config["configurable"]["lane"]) == comms_lane
        mock_resolve.assert_not_awaited()

    @patch("app.helpers.agent_helpers.resolve_lane")
    async def test_an_executor_dispatched_by_comms_resolves_its_own_lane(self, mock_resolve):
        """Comms' OpenAI lane is comms-only: inherited whole, the executor would run on the comms model."""
        executor_lane = ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model="work-model",
            reasoning={"effort": "medium"},
            provider_pin=None,
            max_input_tokens=128_000,
        )
        mock_resolve.return_value = (executor_lane, PlanType.PRO)
        comms_lane = ModelLane(
            provider=LLMProviderName.OPENAI,
            model="comms-model",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=128_000,
        )

        config = await build_agent_config(
            identity=AgentIdentity(conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"),
            thread=AgentThread(base_configurable={"lane": comms_lane.to_configurable()}),
            lane=AgentLane(role=AgentRole.EXECUTOR),
        )

        configurable = config["configurable"]
        assert ModelLane.from_configurable(configurable["lane"]) == executor_lane
        assert configurable["provider"] == LLMProviderName.OPENROUTER
        assert configurable["model"] == "work-model"
        assert mock_resolve.await_args.args[1] is AgentRole.EXECUTOR

    async def test_every_parent_fallback_key_fills_only_its_own_blank(self):
        """Each fallback key inherits from the same key on the parent, and no other — a crossed key would type-check fine since both are str | None."""
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

    async def test_child_value_wins_over_parent_for_fallback_keys(self):
        """The parent only fills a blank — an explicit child value is never clobbered."""

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

    async def test_parent_overrides_child_for_conversation_id_and_user_messages(self):
        """The true conversation id and the user's verbatim turns, established once by comms, must not be overwritten by a child's wrapped id or paraphrase."""

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

    async def test_parent_overrides_child_for_the_verbatim_user_request(self):
        """Same rule as user_messages: comms establishes the verbatim request once, and a child's paraphrase must not overwrite it."""

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

    async def test_a_root_run_carries_its_own_verbatim_request(self):
        """With no parent to inherit from, the value passed in is the one that lands."""

        configurable = (
            await build_agent_config(
                identity=AgentIdentity(
                    conversation_id="conv-1",
                    user=FAKE_USER,
                    agent_name="comms_agent",
                ),
                turn=AgentTurn(
                    user_request="pls archive the junk mail",
                    user_messages=["pls archive the junk mail"],
                ),
            )
        )["configurable"]

        assert configurable["user_request"] == "pls archive the junk mail"
        assert configurable["user_messages"] == ["pls archive the junk mail"]

    async def test_a_handoff_subagent_inherits_preferences_established_by_comms(self) -> None:
        """user_preferences and writing_style follow the same rule as user_messages: established once by comms, a child never has its own copy to prefer."""

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

    async def test_no_parent_and_no_explicit_value_leaves_preferences_absent(self) -> None:
        """A root call site with no onboarding data leaves the key absent rather than fabricating a default."""

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

    async def test_session_id_is_the_conversation_when_there_is_no_parent(self):
        """The sticky-routing key defaults to the conversation id itself."""

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

    async def test_session_id_is_inherited_verbatim_from_the_parent(self):
        """Every agent routes on the parent's sticky key, not its own conversation_id, which is a wrapped thread id."""

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

    async def test_session_id_survives_a_parent_that_carries_none(self):
        """Present-but-None and absent are different: a parent with no sticky key hands down that absence, not an invented one."""

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

    async def test_stream_id_always_comes_from_the_parent(self):
        """Pass-through, not a fallback: a child never invents its own stream."""

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

    async def test_workflow_context_survives_into_a_child_agents_config(self):
        """The executor and its handoff subagents must see the same workflow the comms configurable stamped, or playbook tools refuse."""

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

    async def test_usage_metadata_callback(self):
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

    async def test_selected_tool_and_category(self):
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

    async def test_bot_source_sets_bot_category_and_channel(self) -> None:
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

    async def test_web_source_sets_ui_category(self) -> None:
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

    async def test_missing_source_defaults_to_background(self) -> None:
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

    async def test_source_inherited_from_base_configurable(self) -> None:
        """A child agent inherits the channel from its parent and recomputes the category."""

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


class TestBackgroundAuthorization:
    """Schedule text authorizes background runs the way words authorize live turns."""

    def test_interactive_runs_pass_through_untouched(self) -> None:
        turns = ["send it"]
        assert (
            background_authorization(
                turns,
                execution_mode="interactive",
                workflow_title="Morning briefing",
                todo_title="Brief me",
            )
            is turns
        )

    def test_workflow_definition_is_appended_as_standing_authorization(self) -> None:
        out = background_authorization(
            ["Execute workflow: Morning briefing"],
            execution_mode="background",
            workflow_title="Morning briefing",
            workflow_description="Emails my calendar and top emails",
        )
        assert out[0] == "Execute workflow: Morning briefing"
        assert out[1] == "Scheduled workflow: Morning briefing. Emails my calendar and top emails"

    @pytest.mark.parametrize(
        ("title", "description", "expected"),
        [
            ("Morning briefing", "", "Scheduled workflow: Morning briefing"),
            ("", "Emails my calendar", "Scheduled workflow. Emails my calendar"),
        ],
    )
    def test_either_display_field_alone_still_authorizes(
        self, title: str, description: str, expected: str
    ) -> None:
        out = background_authorization(
            ["run it"],
            execution_mode="background",
            workflow_title=title,
            workflow_description=description,
        )
        assert out == ["run it", expected]

    def test_generated_content_never_authorizes(self) -> None:
        # Steps and execution prompts may be LLM-generated (GeneratedStep), so the
        # function does not even accept them — only human-written display fields
        # travel. A generated step naming a recipient grounds nothing.
        params = set(inspect.signature(background_authorization).parameters)
        assert "workflow_steps" not in params
        assert "workflow_prompt" not in params

    def test_todo_title_is_added_unless_the_prompt_covers_it(self) -> None:
        assert background_authorization(
            ["check calendar and brief me"], execution_mode="background", todo_title="Brief me"
        ) == ["check calendar and brief me", "Tracked todo: Brief me"]
        assert background_authorization(
            ["Brief me on today"], execution_mode="background", todo_title="Brief me"
        ) == ["Brief me on today"]

    def test_a_run_with_no_schedule_text_is_unchanged(self) -> None:
        turns = ["health check"]
        assert background_authorization(turns, execution_mode="background") is turns


# ---------------------------------------------------------------------------
# _stamp_langfuse
# ---------------------------------------------------------------------------


class TestStampLangfuse:
    """The exact keys the Langfuse SDK reads by name.

    A renamed or blanked key does not fail anywhere in GAIA — the trace
    silently loses that dimension. Pinning the whole dict, not key-by-key
    membership, is what makes a rename visible.
    """

    def test_a_traced_run_stamps_every_langfuse_key_by_name(self):
        configurable = {}
        metadata = {}

        _stamp_langfuse(
            configurable,
            metadata,
            "trace-abc",
            ["tag-one"],
            USER_ID,
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
        """No trace id means no Langfuse binding anywhere, not even the tags."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, None, None, USER_ID, CONV_ID)

        assert configurable == {}
        assert metadata == {}

    def test_tags_reach_the_configurable_even_without_a_trace_id(self):
        """Tags are stamped from their own guard, so a child inherits them even when this run has no trace of its own."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, None, ["tag-one"], USER_ID, CONV_ID)

        assert configurable == {"langfuse_tags": ["tag-one"]}
        assert metadata == {}

    def test_an_anonymous_user_leaves_the_user_dimension_off(self):
        """A background run has no user id, so Langfuse gets no user key at all rather than a null one."""
        configurable = {}
        metadata = {}

        _stamp_langfuse(configurable, metadata, "trace-abc", None, None, CONV_ID)

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


class TestBuildAgentCallbacks:
    @patch("app.helpers.agent_helpers.build_langfuse_callback", return_value=None)
    def test_every_run_carries_the_provider_ttft_callback(self, _mock_langfuse):
        """The callback is the only source of true provider first-token latency, on every tier."""

        callbacks = _build_agent_callbacks(None)

        assert len(callbacks) == 1
        assert isinstance(callbacks[0], LLMTtftCallback)


class TestBuildAgentConfigCallbackWiring:
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    @patch("app.helpers.agent_helpers._build_agent_callbacks")
    async def test_the_runs_usage_callback_reaches_the_callbacks(
        self, mock_build_callbacks, mock_resolve
    ):
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

        assert mock_build_callbacks.call_args.args == (usage_cb,)


class TestBuildAgentConfigLaneResolution:
    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_top_level_run_resolves_its_lane_from_user_role_and_dev_pick(
        self, mock_resolve
    ):
        """resolve_lane is the single place a model is chosen, from the user id, role and dev option together."""
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

    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_child_run_inherits_the_parent_lane_without_resolving(self, mock_resolve):
        """Inheritance beats resolving fresh: a child that re-resolves can land on a different model mid-conversation."""
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

    @patch("app.helpers.agent_helpers.resolve_lane", new_callable=AsyncMock)
    async def test_a_dev_model_pick_beats_an_inherited_lane(self, mock_resolve):
        """An explicit dev choice outranks the parent's lane, so the run resolves rather than inherits."""
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


class TestBuildAgentConfigLaneMetadata:
    async def test_metadata_carries_the_lanes_provider_and_model(self):
        """The TTFT callback reads its labels off run metadata, so the resolved lane must land there."""
        lane = ModelLane(
            provider=LLMProviderName.GEMINI,
            model="gemini-flash",
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
            thread=AgentThread(base_configurable={"lane": lane.to_configurable()}),
        )

        assert config["metadata"]["lane_provider"] == "gemini"
        assert config["metadata"]["lane_model"] == "gemini-flash"

    async def test_a_lane_with_no_model_metadata_says_default(self):
        """The custom dev endpoint pins no model, so metadata reads "default" rather than a null."""
        lane = ModelLane(
            provider=LLMProviderName.CUSTOM,
            model=None,
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
            thread=AgentThread(base_configurable={"lane": lane.to_configurable()}),
        )

        assert config["metadata"]["lane_provider"] == "custom"
        assert config["metadata"]["lane_model"] == "default"


class TestBuildAgentConfigLangfuseWiring:
    async def test_the_stamp_names_this_conversation_and_this_user(self):
        """Everything the trace is bound to comes from this one call: trace, session, user and tags."""

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

    async def test_a_child_lands_on_the_parents_trace_and_tags(self):
        """A child agent passes no tracing of its own, so its spans join the comms trace rather than starting a second one."""

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

    async def test_explicit_tracing_beats_what_the_parent_carried(self):
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

    async def test_an_empty_tag_list_clears_the_parents_tags(self):
        """The precedence test is "is not None", not truthiness, so a caller can pass [] to mean "no tags" instead of "inherit"."""

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
    async def test_a_workflow_without_a_title_inherits_the_documented_defaults(self):
        """No title and no notify preference still produce a titled-by-empty-string, notify-by-default config."""

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


class TestBuildAgentConfigPresence:
    """Where the user is: captured once at the run tree's root and inherited by every child."""

    TURN: ClassVar[PresenceSnapshot] = {"captured_at": 1_800_000_000, "last_seen": {"telegram": 1}}
    STORED: ClassVar[PresenceSnapshot] = {"captured_at": 1_800_000_500, "last_seen": {"web": 2}}

    @patch("app.helpers.agent_helpers.read_presence", new_callable=AsyncMock)
    async def test_a_root_run_with_no_presence_reads_it_once(self, mock_read):
        mock_read.return_value = self.STORED

        config = await build_agent_config(
            identity=AgentIdentity(conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"),
        )

        mock_read.assert_awaited_once_with(USER_ID)
        assert config["configurable"]["presence"] == self.STORED

    @patch("app.helpers.agent_helpers.read_presence", new_callable=AsyncMock)
    async def test_the_turns_own_presence_wins_and_reads_nothing(self, mock_read):
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=CONV_ID, user=FAKE_USER, agent_name="comms_agent"
            ),
            thread=AgentThread(base_configurable={"presence": self.STORED}),
            turn=AgentTurn(presence=self.TURN),
        )

        mock_read.assert_not_awaited()
        assert config["configurable"]["presence"] == self.TURN

    @patch("app.helpers.agent_helpers.read_presence", new_callable=AsyncMock)
    async def test_an_executor_child_inherits_its_parents_presence(self, mock_read):
        config = await build_agent_config(
            identity=AgentIdentity(conversation_id=CONV_ID, user=FAKE_USER, agent_name="executor"),
            thread=AgentThread(base_configurable={"presence": self.TURN}),
        )

        mock_read.assert_not_awaited()
        assert config["configurable"]["presence"] == self.TURN


# ---------------------------------------------------------------------------
# _collect_silent_tool_entries
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _accumulate_silent_custom_event
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _hold_silent_chunk
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _record_interruption_quietly
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Async iterator helper
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item
