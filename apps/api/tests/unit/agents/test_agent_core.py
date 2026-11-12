"""Unit tests for app.agents.core.agent — call_agent and its setup."""

from collections.abc import AsyncGenerator
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core import agent as agent_module
from app.agents.core.agent import (
    AgentRunOptions,
    StreamMessageIds,
    _core_agent_logic,
    call_agent,
)
from app.agents.llm.lane import AgentRole
from app.config.settings import settings
from app.constants.graphs import GraphName
from app.constants.llm import DEV_MODEL_OPTIONS
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTracing,
    AgentTurn,
    recent_user_messages,
)
from app.models.agent_models import agent_user_context
from app.models.message_models import (
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser
from shared.py.analytics import UserId
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunFailed, AgentRunStarted
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import (
    AnalyticsContext,
    analytics_context,
    current_analytics_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


USER_ID = "6812f0b3c9a14e2b7d5a91cc"


def _make_request(**overrides: object) -> MessageRequestWithHistory:
    defaults: dict[str, object] = {
        "message": "Hello agent",
        "messages": [{"role": "user", "content": "Hello agent"}],
        "fileIds": [],
        "fileData": [],
        "selectedTool": None,
        "toolCategory": None,
        "selectedWorkflow": None,
        "selectedCalendarEvent": None,
        "replyToMessage": None,
    }
    defaults.update(overrides)
    return MessageRequestWithHistory.model_validate(defaults)


def _make_user(**overrides: object) -> AuthenticatedUser:
    defaults: dict[str, object] = {
        "user_id": USER_ID,
        "email": "test@example.com",
        "name": "Test User",
    }
    defaults.update(overrides)
    return AuthenticatedUser.model_validate(defaults)


FAKE_HISTORY = [
    SystemMessage(content="You are helpful."),
    HumanMessage(content="Hello agent"),
]
FAKE_GRAPH = MagicMock(name="fake_graph")
FAKE_STATE = {"messages": FAKE_HISTORY, "query": "Hello agent"}
FAKE_CONFIG = {
    "configurable": {
        "thread_id": "conv-1",
        "user_id": USER_ID,
        # The lane's expanded binding key — `model_name` is no longer part of the
        # configurable contract.
        "model": "gpt-4o",
    }
}


# ---------------------------------------------------------------------------
# Patches common to most tests
# ---------------------------------------------------------------------------


#: What a root run with no presence of its own reads from the store.
READ_PRESENCE: PresenceSnapshot = {"captured_at": 1_700_000_000, "last_seen": {"telegram": 1}}


@pytest.fixture(autouse=True)
def _read_presence():
    """Keep the root's presence read off real Redis; tests that care assert on this mock."""
    with patch(
        "app.agents.core.agent.read_presence", new_callable=AsyncMock, return_value=READ_PRESENCE
    ) as read:
        yield read


@pytest.fixture(autouse=True)
def _no_real_analytics():
    """Keep every test hermetic: agent lifecycle events are asserted through this mock and never reach a real PostHog client."""
    with patch("app.services.analytics_service.capture") as mock_capture:
        yield mock_capture


def _common_patches():
    """Return a dict of mock targets for the core agent module."""
    return {
        "construct": patch(
            "app.agents.core.agent.construct_langchain_messages",
            new_callable=AsyncMock,
            return_value=FAKE_HISTORY,
        ),
        "get_graph": patch(
            "app.agents.core.agent.GraphManager.get_graph",
            new_callable=AsyncMock,
            return_value=FAKE_GRAPH,
        ),
        "build_state": patch(
            "app.agents.core.agent.build_initial_state",
            return_value=FAKE_STATE,
        ),
        # Model selection now happens INSIDE build_agent_config (it resolves the
        # lane), so patching it replaces the whole thing — no separate
        # plan-routing / dev-override mutations to stub out.
        "build_config": patch(
            "app.agents.core.agent.build_agent_config",
            new_callable=AsyncMock,
            return_value=FAKE_CONFIG,
        ),
        "log": patch("app.agents.core.agent.log"),
    }


async def _drain(stream: AsyncGenerator[str, None]) -> list[str]:
    """Run a streaming turn to its end and return every frame it yielded."""
    return [chunk async for chunk in stream]


# ---------------------------------------------------------------------------
# _core_agent_logic
# ---------------------------------------------------------------------------


class TestCoreAgentLogic:
    """Tests for the shared _core_agent_logic helper."""

    @pytest.mark.asyncio
    async def test_returns_graph_state_config(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"] as get_graph,
            patches["build_state"],
            patches["build_config"],
            patches["log"],
        ):
            graph, state, config = await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        # The user's turn runs on the comms graph, whose thread is the conversation.
        get_graph.assert_awaited_once_with(GraphName.COMMS)
        assert graph is FAKE_GRAPH
        assert state is FAKE_STATE
        assert config is FAKE_CONFIG

    @pytest.mark.asyncio
    async def test_construct_messages_receives_correct_args(self):
        req = _make_request(message="custom query")
        user = _make_user(name="Alice")
        patches = _common_patches()
        with (
            patches["construct"] as mock_construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=user,
            )

        mock_construct.assert_awaited_once()
        kwargs = mock_construct.call_args.kwargs
        assert kwargs["query"] == "custom query"
        assert kwargs["scope"].user_name == "Alice"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("history", "expected"),
        [
            ([{"role": "user", "content": "Hello agent"}], True),
            (
                [
                    {"role": "assistant", "content": "Your reminder: stretch"},
                    {"role": "user", "content": "Hello agent"},
                ],
                False,
            ),
        ],
        ids=["first_turn", "later_turn"],
    )
    async def test_scope_marks_whether_the_turn_opens_the_thread(self, history, expected):
        patches = _common_patches()
        with (
            patches["construct"] as mock_construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(messages=history),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert mock_construct.call_args.kwargs["scope"].opens_thread is expected

    @pytest.mark.asyncio
    async def test_the_users_onboarding_data_reaches_build_agent_config(self):
        """Onboarding_preferences(user.get("onboarding")) is real, unmocked code in _core_agent_logic — this proves the pair it derives actually lands on the build_agent_config call (so the executor and every subagent it hands off to can inherit it), not just that extraction doesn't crash."""
        user = _make_user(
            onboarding={
                "preferences": {"profession": "engineer"},
                "writing_style": {"summary": "terse"},
            }
        )
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["log"],
        ):
            await _core_agent_logic(request=_make_request(), conversation_id="conv-1", user=user)

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["turn"].user_preferences == {"profession": "engineer"}
        assert kwargs["turn"].writing_style == {"summary": "terse"}

    async def test_a_run_without_presence_reads_it_once_for_comms_and_the_config(
        self, _read_presence: AsyncMock
    ) -> None:
        """A turn that captured none reads it once: that read feeds the comms context and every child."""
        patches = _common_patches()
        with (
            patches["construct"] as construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as build_config,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        _read_presence.assert_awaited_once_with(USER_ID)
        assert construct.call_args.kwargs["scope"].presence == READ_PRESENCE
        assert build_config.call_args.kwargs["turn"].presence == READ_PRESENCE

    async def test_the_presence_an_interactive_turn_captured_wins_without_a_read(
        self, _read_presence: AsyncMock
    ) -> None:
        captured: PresenceSnapshot = {"captured_at": 5, "last_seen": {"web": 4}}
        patches = _common_patches()
        with (
            patches["construct"] as construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as build_config,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                options=AgentRunOptions(source="web", presence=captured),
            )

        _read_presence.assert_not_awaited()
        assert construct.call_args.kwargs["scope"].presence == captured
        assert build_config.call_args.kwargs["turn"].presence == captured

    @pytest.mark.asyncio
    async def test_interactive_chat_carries_no_workflow_on_the_turn(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(), conversation_id="conv-1", user=_make_user()
            )

        assert mock_build_config.call_args.kwargs["turn"].workflow_id is None

    @pytest.mark.asyncio
    async def test_log_set_called_with_agent_metadata(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=_make_request(
                    selectedWorkflow=SelectedWorkflowData(
                        id="wf-1", title="Wf", description="d", steps=[]
                    ),
                    selectedCalendarEvent=SelectedCalendarEventData(
                        id="evt-1", summary="Evt", description="d", start={}, end={}
                    ),
                    replyToMessage=ReplyToMessageData(id="msg-1", content="hi", role="user"),
                ),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_log.set.assert_called_once()
        call_kwargs = mock_log.set.call_args.kwargs
        # Exact dict, not a subset: these flags are what separates a workflow
        # run from chat in the operator's view of the event stream.
        assert call_kwargs["agent"] == {
            "model": "gpt-4o",
            "has_workflow": True,
            "has_calendar_event": True,
            "has_reply": True,
            "history_message_count": len(FAKE_HISTORY),
        }


# ---------------------------------------------------------------------------
# call_agent (streaming)
# ---------------------------------------------------------------------------


class TestCallAgent:
    """Tests for call_agent (streaming mode)."""

    @pytest.mark.asyncio
    async def test_returns_streaming_generator(self):
        """Happy path: returns the generator from execute_graph_streaming."""

        async def _fake_stream(*args, **kwargs):
            yield "data: {}\n\n"
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ),
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

        assert len(chunks) == 2
        assert "DONE" in chunks[-1]

    @pytest.mark.asyncio
    async def test_a_turn_in_a_todos_chat_reaches_the_model_bound_to_that_todo(self):
        """Regression: call_agent rebuilt the options field by field and dropped the todo binding."""

        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"] as construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as build_config,
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ),
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                    options=AgentRunOptions(source="web", active_todo_id="todo-7"),
                )
            )

        assert construct.call_args.kwargs["scope"].active_todo_id == "todo-7"
        assert build_config.call_args.kwargs["turn"].active_todo_id == "todo-7"
        assert build_config.call_args.kwargs["turn"].source == "web"

    @pytest.mark.asyncio
    async def test_stream_id_added_to_config(self):
        """When stream_id is provided, it should appear in config."""

        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        def capture_config():
            original_return = FAKE_CONFIG.copy()
            original_return["configurable"] = FAKE_CONFIG["configurable"].copy()
            return original_return

        patches = _common_patches()
        # Use a side_effect on build_agent_config to capture the config
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                return_value={
                    "configurable": {
                        "thread_id": "conv-1",
                        "user_id": USER_ID,
                        "model_name": "gpt-4o",
                    }
                },
            ),
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                    ids=StreamMessageIds(stream_id="stream-abc"),
                )
            )

            # The config passed to execute_graph_streaming should have stream_id
            call_args = mock_exec.call_args
            passed_config = call_args[0][2]  # third positional arg
            assert passed_config["configurable"]["stream_id"] == "stream-abc"

    @pytest.mark.asyncio
    async def test_no_stream_id_when_not_provided(self):
        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                return_value={
                    "configurable": {
                        "thread_id": "conv-1",
                        "user_id": USER_ID,
                        "model_name": "gpt-4o",
                    }
                },
            ),
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

            passed_config = mock_exec.call_args[0][2]
            assert "stream_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_bot_message_id_added_to_config(self):
        """A HIL pause on this turn's executor resumes onto this SAME bot message."""

        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value={
                    "configurable": {
                        "thread_id": "conv-1",
                        "user_id": USER_ID,
                        "model_name": "gpt-4o",
                    }
                },
            ),
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                    ids=StreamMessageIds(bot_message_id="bot-msg-7"),
                )
            )

            passed_config = mock_exec.call_args[0][2]
            assert passed_config["configurable"]["bot_message_id"] == "bot-msg-7"

    @pytest.mark.asyncio
    async def test_user_message_id_added_to_config(self):
        """The executor links its notifications back to the user's message by this id."""

        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=_fresh_config(),
            ),
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                    ids=StreamMessageIds(user_message_id="user-msg-3"),
                )
            )

        passed_config = mock_exec.call_args[0][2]
        assert passed_config["configurable"]["user_message_id"] == "user-msg-3"

    @pytest.mark.asyncio
    async def test_no_bot_message_id_when_not_provided(self):
        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value={
                    "configurable": {
                        "thread_id": "conv-1",
                        "user_id": USER_ID,
                        "model_name": "gpt-4o",
                    }
                },
            ),
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

            passed_config = mock_exec.call_args[0][2]
            assert "bot_message_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_error_returns_error_generator(self):
        """When _core_agent_logic raises, call_agent returns an error SSE stream."""
        patches = _common_patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

        assert chunks == [
            f"data: {json.dumps({'error': 'Error when calling agent: boom'})}\n\n",
            "data: [DONE]\n\n",
        ]

    @pytest.mark.asyncio
    async def test_error_generator_format(self):
        """Error generator yields proper SSE format."""
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=ValueError("bad input"),
            ),
            patch(
                "app.agents.core.agent.GraphManager.get_graph",
                new_callable=AsyncMock,
                return_value=FAKE_GRAPH,
            ),
            patch("app.agents.core.agent.build_initial_state", return_value=FAKE_STATE),
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=FAKE_CONFIG,
            ),
            patch("app.agents.core.agent.log"),
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

        # Each chunk should end with \n\n (SSE format)
        for chunk in chunks:
            assert chunk.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_run_lifecycle_events_captured(self, _no_real_analytics):
        """STARTED before the stream, COMPLETED after it ends normally."""

        async def _fake_stream(*args, **kwargs):
            yield "data: {}\n\n"
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_stream,
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

        assert len(chunks) == 2

        events = [type(c.args[1]) for c in _no_real_analytics.call_args_list]
        assert events == [
            AgentRunStarted,
            AgentRunCompleted,
        ]
        assert _no_real_analytics.call_args_list[0].args == (
            UserId(USER_ID),
            AgentRunStarted(agent="comms", mode="interactive", conversation_id="conv-1"),
        )
        assert _no_real_analytics.call_args_list[1].args == (
            UserId(USER_ID),
            AgentRunCompleted(agent="comms", mode="interactive", conversation_id="conv-1"),
        )
        assert all(arg is not None for arg in mock_stream.call_args.args)

    @pytest.mark.asyncio
    async def test_stream_failure_captures_failed(self, _no_real_analytics):
        """An exception mid-stream yields FAILED and still propagates."""

        async def _failing_stream(*args, **kwargs):
            yield "data: {}\n\n"
            raise RuntimeError("graph exploded")

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_failing_stream(),
            ),
            pytest.raises(RuntimeError, match="graph exploded"),
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )

        events = [type(c.args[1]) for c in _no_real_analytics.call_args_list]
        assert events == [AgentRunStarted, AgentRunFailed]
        assert _no_real_analytics.call_args_list[1].args == (
            UserId(USER_ID),
            AgentRunFailed(
                agent="comms", mode="interactive", conversation_id="conv-1", reason="RuntimeError"
            ),
        )

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_setup_error_is_a_started_run_that_failed(self, _no_real_analytics):
        """Regression: a setup failure emitted run_failed with no run_started before it."""
        patches = _common_patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )
            )
        assert len(chunks) == 2

        events = [type(c.args[1]) for c in _no_real_analytics.call_args_list]
        assert events == [AgentRunStarted, AgentRunFailed]
        assert _no_real_analytics.call_args_list[1].args == (
            UserId(USER_ID),
            AgentRunFailed(
                agent="comms", mode="interactive", conversation_id="conv-1", reason="RuntimeError"
            ),
        )
        mock_log.error.assert_called_once()
        assert "Error when calling agent" in mock_log.error.call_args.args[0]
        assert mock_log.error.call_args.kwargs["error_type"] == "RuntimeError"
        assert mock_log.error.call_args.kwargs["error"] == "boom"

    @pytest.mark.asyncio
    async def test_a_users_turn_records_the_comms_run_as_agent_work(self, _no_real_analytics):
        """Greptile #1337: the run events took the request's actor=user, so agent work read as human activity."""

        async def _failing_stream(*args, **kwargs):
            yield "data: {}\n\n"
            raise RuntimeError("graph exploded")

        actors: list[Actor] = []
        _no_real_analytics.side_effect = lambda *_, **__: actors.append(
            current_analytics_context().attribution.actor
        )
        users_turn = AnalyticsContext(
            attribution=Attribution(
                actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
            )
        )
        patches = _common_patches()
        with (
            analytics_context(users_turn),
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_failing_stream(),
            ),
        ):
            with pytest.raises(RuntimeError, match="graph exploded"):
                await _drain(
                    call_agent(request=_make_request(), conversation_id="conv-1", user=_make_user())
                )
            assert current_analytics_context() == users_turn

        assert actors == [Actor.AGENT, Actor.AGENT]

    @pytest.mark.asyncio
    async def test_missing_user_id_skips_events(self, _no_real_analytics):
        """No user id -> the run still works but nothing is captured."""

        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ),
        ):
            chunks = await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(user_id=""),
                )
            )

        assert len(chunks) == 1
        _no_real_analytics.assert_not_called()


# ---------------------------------------------------------------------------
# the lane the top-level run resolves
# ---------------------------------------------------------------------------


def _fresh_config() -> dict:
    """Build a config object this test owns.

    _core_agent_logic MUTATES config["configurable"], so the shared
    module-level FAKE_CONFIG cannot be used by anything that asserts on those
    writes — one test would see the previous test's key.
    """
    return {"configurable": {"thread_id": "conv-1", "user_id": USER_ID, "model": "gpt-4o"}}


class TestTheLaneTheRunResolves:
    """Assemble the top-level run: build_agent_config resolves the comms lane here and the executor plus every subagent inherit it whole.

    Everything the run is has to reach that one call — a blanked or dropped argument is a turn that
    silently loses its tool scope, its trace, or its identity.
    """

    @pytest.mark.asyncio
    async def test_every_field_the_run_carries_reaches_build_agent_config(self):
        request = _make_request(selectedTool="web_search", toolCategory="research")
        user = _make_user()
        callback = MagicMock()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            # dev_option is None only in production: with ENV unpinned this passes
            # in CI (no .env) but fails on developer machines, where apps/api/.env
            # sets ENV=development. Pinned like TestTheDevModelSelector.
            patch.object(agent_module.settings, "ENV", "production"),
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=_fresh_config(),
            ) as build_config,
            patches["log"],
            # Pinned as the dev-selector classes below do: the dev model menu is
            # live only in development, and a developer's .env sets ENV=development,
            # so an unpinned run resolves DEV_DEFAULT_MODEL and holds only in CI.
            patch.object(agent_module.settings, "ENV", "production"),
        ):
            await _core_agent_logic(
                request=request,
                conversation_id="conv-1",
                user=user,
                options=AgentRunOptions(
                    usage_metadata_callback=callback,
                    source="web",
                    langfuse_trace_id="trace-1",
                    langfuse_tags=["tag-a"],
                ),
            )

        assert build_config.call_args.args == ()
        # Dataclass equality, so this is exactly as strict as the flat-kwargs dict
        # it replaced: every field of every group has to match, and an argument
        # dropped on the floor shows up as a default that is not the value here.
        assert build_config.call_args.kwargs == {
            "identity": AgentIdentity(
                conversation_id="conv-1",
                user=agent_user_context(user),
                agent_name="comms_agent",
            ),
            "lane": AgentLane(role=AgentRole.COMMS, dev_option=None),
            "turn": AgentTurn(
                selected_tool="web_search",
                tool_category="research",
                active_todo_id=None,
                execution_mode="interactive",
                source="web",
                user_messages=recent_user_messages(request.messages, request.message),
                user_request=request.message,
                user_preferences=None,
                writing_style=None,
                presence=READ_PRESENCE,
            ),
            "tracing": AgentTracing(
                usage_metadata_callback=callback,
                langfuse_trace_id="trace-1",
                langfuse_tags=["tag-a"],
            ),
        }

    @pytest.mark.asyncio
    async def test_a_turn_in_a_tracked_todos_chat_is_bound_to_that_todo(self):
        """The user is talking about this todo, live: bound to it, still interactive."""
        patches = _common_patches()
        with (
            patches["construct"] as construct,
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=_fresh_config(),
            ) as build_config,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                options=AgentRunOptions(active_todo_id="todo-7"),
            )

        turn = build_config.call_args.kwargs["turn"]
        assert (turn.active_todo_id, turn.execution_mode) == ("todo-7", "interactive")
        # The comms context names the todo too, not just the config the executor inherits.
        assert construct.call_args.kwargs["scope"].active_todo_id == "todo-7"


class TestTheDevModelSelector:
    """DEV-ONLY: the chat-header model picker.

    It wins over plan routing inside resolve_lane, and must be inert in production.
    """

    async def _dev_option_for(self, request, env="development", dev_default=None):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=_fresh_config(),
            ) as build_config,
            patches["log"],
            patch.object(agent_module.settings, "ENV", env),
            patch.object(settings, "DEV_DEFAULT_MODEL", dev_default),
        ):
            await _core_agent_logic(request=request, conversation_id="conv-1", user=_make_user())
        return build_config.call_args.kwargs["lane"].dev_option

    @pytest.mark.asyncio
    async def test_an_explicit_comms_pick_becomes_the_runs_dev_option(self):
        option = await self._dev_option_for(
            _make_request(comms_model="minimax-m3", use_default_models=False)
        )

        assert option == DEV_MODEL_OPTIONS["minimax-m3"]

    @pytest.mark.asyncio
    async def test_expressing_no_preference_takes_the_env_configured_default(self):
        """Use_default_models is what routes bots, scripts and plain requests onto the dev model too, so it cannot be ignored here."""
        option = await self._dev_option_for(
            _make_request(comms_model=None, use_default_models=True),
            dev_default="deepseek-v4",
        )

        assert option == DEV_MODEL_OPTIONS["deepseek-v4"]

    @pytest.mark.asyncio
    async def test_production_never_resolves_a_dev_option(self):
        option = await self._dev_option_for(
            _make_request(comms_model="minimax-m3", use_default_models=False),
            env="production",
        )

        assert option is None


class TestTheExecutorsOwnDevModel:
    """The executor builds its own configurable and would otherwise inherit comms's lane, so its dev pick rides down on the configurable for prepare_executor_execution to resolve."""

    async def _configurable(self, request, env="development", dev_default=None):
        config = _fresh_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patches["log"],
            patch.object(agent_module.settings, "ENV", env),
            patch.object(settings, "DEV_DEFAULT_MODEL", dev_default),
        ):
            await _core_agent_logic(request=request, conversation_id="conv-1", user=_make_user())
        return config["configurable"]

    @pytest.mark.asyncio
    async def test_an_explicit_executor_pick_is_stashed_for_the_executor(self):
        configurable = await self._configurable(
            _make_request(executor_model="minimax-m3", use_default_models=False)
        )

        assert configurable["dev_executor_model"] == "minimax-m3"

    @pytest.mark.asyncio
    async def test_expressing_no_preference_stashes_the_env_configured_default(self):
        configurable = await self._configurable(
            _make_request(executor_model=None, use_default_models=True),
            dev_default="deepseek-v4",
        )

        assert configurable["dev_executor_model"] == "deepseek-v4"

    @pytest.mark.asyncio
    async def test_no_executor_pick_leaves_the_key_off_entirely(self):
        """Absent, not None: the executor treats a present key as a real choice."""
        configurable = await self._configurable(
            _make_request(executor_model=None, use_default_models=False)
        )

        assert "dev_executor_model" not in configurable

    @pytest.mark.asyncio
    async def test_production_never_stashes_a_dev_executor_model(self):
        configurable = await self._configurable(
            _make_request(executor_model="minimax-m3", use_default_models=False),
            env="production",
        )

        assert "dev_executor_model" not in configurable


# ---------------------------------------------------------------------------
# what each entry point hands down
# ---------------------------------------------------------------------------


class TestTheOptionsEachEntryPointDerives:
    """call_agent re-packs its own arguments into a fresh AgentRunOptions for _core_agent_logic.

    Every field is a run property that has no second source: a blanked or dropped one is a turn
    that loses its token accounting, its surface, or its Langfuse trace, and the run still
    completes normally. The whole object is compared, so an extra or missing field fails too. The
    stand-in carries _core_agent_logic's real signature so a dropped positional argument raises
    here rather than quietly rebinding.
    """

    @staticmethod
    def _recording_core(seen: list, config: dict):
        async def _fake_core(
            request,
            conversation_id,
            user,
            options=None,
        ):
            seen.append((conversation_id, options))
            return FAKE_GRAPH, FAKE_STATE, config

        return _fake_core

    @pytest.mark.asyncio
    async def test_streaming_hands_core_the_callback_source_trace_and_tags(self):
        async def _fake_stream(*args, **kwargs):
            yield "data: [DONE]\n\n"

        seen: list = []
        callback = MagicMock(name="usage_metadata_callback")
        patches = _common_patches()
        with (
            patches["log"],
            patch(
                "app.agents.core.agent._core_agent_logic",
                new=self._recording_core(seen, _fresh_config()),
            ),
            patch(
                "app.agents.core.agent.trace_id_for_message", return_value="trace-9"
            ) as trace_id_for,
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ),
        ):
            await _drain(
                call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                    options=AgentRunOptions(usage_metadata_callback=callback, source="whatsapp"),
                    ids=StreamMessageIds(bot_message_id="bot-7"),
                )
            )

        trace_id_for.assert_called_once_with("bot-7")
        assert seen == [
            (
                "conv-1",
                AgentRunOptions(
                    usage_metadata_callback=callback,
                    source="whatsapp",
                    langfuse_trace_id="trace-9",
                    langfuse_tags=["comms_agent", settings.ENV],
                ),
            )
        ]
