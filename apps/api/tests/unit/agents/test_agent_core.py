"""Unit tests for app.agents.core.agent — call_agent and call_agent_silent."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core import agent as agent_module
from app.agents.core.agent import (
    _core_agent_logic,
    call_agent,
    call_agent_silent,
)
from app.agents.llm import lane as lane_module
from app.agents.llm.lane import AgentRole
from app.constants.llm import DEV_MODEL_OPTIONS
from app.helpers.agent_helpers import recent_user_messages
from app.models.message_models import (
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.services.analytics_service import AnalyticsEvents

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**overrides) -> MessageRequestWithHistory:
    defaults = {
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
    return MessageRequestWithHistory(**defaults)  # type: ignore[arg-type]  # fixture spreads an untyped defaults dict into the model


def _make_user(**overrides) -> dict:
    defaults = {
        "user_id": "user-123",
        "email": "test@example.com",
        "name": "Test User",
    }
    defaults.update(overrides)
    return defaults


FAKE_HISTORY = [
    SystemMessage(content="You are helpful."),
    HumanMessage(content="Hello agent"),
]
FAKE_GRAPH = MagicMock(name="fake_graph")
FAKE_STATE = {"messages": FAKE_HISTORY, "query": "Hello agent"}
FAKE_CONFIG = {
    "configurable": {
        "thread_id": "conv-1",
        "user_id": "user-123",
        # The lane's expanded binding key — `model_name` is no longer part of the
        # configurable contract.
        "model": "gpt-4o",
    }
}


# ---------------------------------------------------------------------------
# Patches common to most tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_analytics():
    """Keep every test hermetic: agent lifecycle events are asserted through
    this mock and never reach a real PostHog client."""
    with patch("app.agents.core.agent.capture_event") as mock_capture:
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
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
        ):
            graph, state, config = await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

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
        assert kwargs["user_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_the_users_onboarding_data_reaches_build_agent_config(self):
        """``onboarding_preferences(user.get("onboarding"))`` is real, unmocked
        code in ``_core_agent_logic`` — this proves the pair it derives actually
        lands on the ``build_agent_config`` call (so the executor and every
        subagent it hands off to can inherit it), not just that extraction
        doesn't crash."""
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
        assert kwargs["user_preferences"] == {"profession": "engineer"}
        assert kwargs["writing_style"] == {"summary": "terse"}

    @pytest.mark.asyncio
    async def test_passes_trigger_context(self):
        patches = _common_patches()
        trigger = {"type": "gmail", "email_data": {}}
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"] as mock_build_state,
            patches["build_config"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context=trigger,
            )

        # build_initial_state gets the trigger_context
        assert mock_build_state.call_args.args[4] is trigger

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
                trigger_context={"workflow_id": "wf-1"},
            )

        mock_log.set.assert_called_once()
        call_kwargs = mock_log.set.call_args.kwargs
        # Exact dict, not a subset: these flags are what separates a workflow
        # run from chat in the operator's view of the event stream.
        assert call_kwargs["agent"] == {
            "model": "gpt-4o",
            "has_workflow": True,
            "has_trigger_context": True,
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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        chunks = [chunk async for chunk in gen]
        assert len(chunks) == 2
        assert "DONE" in chunks[-1]

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
                        "user_id": "user-123",
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
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                stream_id="stream-abc",
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
                        "user_id": "user-123",
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
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

            passed_config = mock_exec.call_args[0][2]
            assert "stream_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_bot_message_id_added_to_config(self):
        """A HIL pause on this turn's executor resumes onto this SAME bot message.
        Losing the id there mints a rival message and the user watches the wrong
        one."""

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
                        "user_id": "user-123",
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
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                bot_message_id="bot-msg-7",
            )

            passed_config = mock_exec.call_args[0][2]
            assert passed_config["configurable"]["bot_message_id"] == "bot-msg-7"

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
                        "user_id": "user-123",
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
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        chunks = [chunk async for chunk in gen]
        assert len(chunks) == 2
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert "error" in parsed
        assert "boom" in parsed["error"]
        assert "DONE" in chunks[1]

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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        chunks = [chunk async for chunk in gen]
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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_STARTED]

        chunks = [chunk async for chunk in gen]
        assert len(chunks) == 2

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [
            AnalyticsEvents.AGENT_RUN_STARTED,
            AnalyticsEvents.AGENT_RUN_COMPLETED,
        ]
        started = _no_real_analytics.call_args_list[0]
        assert started.args[0] == "user-123"
        assert started.args[2] == {
            "agent": "comms",
            "mode": "interactive",
            "conversation_id": "conv-1",
        }
        completed = _no_real_analytics.call_args_list[1]
        assert completed.args[0] == "user-123"
        assert completed.args[2] == {
            "agent": "comms",
            "mode": "interactive",
            "conversation_id": "conv-1",
        }
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
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        with pytest.raises(RuntimeError, match="graph exploded"):
            _ = [chunk async for chunk in gen]

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_STARTED, AnalyticsEvents.AGENT_RUN_FAILED]
        failed = _no_real_analytics.call_args_list[1]
        assert failed.args[0] == "user-123"
        assert failed.args[2] == {
            "agent": "comms",
            "mode": "interactive",
            "conversation_id": "conv-1",
        }

    @pytest.mark.asyncio
    async def test_setup_error_captures_failed(self, _no_real_analytics):
        """Setup failure (before the stream exists) still emits FAILED."""
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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )
        chunks = [chunk async for chunk in gen]
        assert len(chunks) == 2

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_FAILED]
        failed = _no_real_analytics.call_args_list[0]
        assert failed.args[0] == "user-123"
        assert failed.args[2] == {
            "agent": "comms",
            "mode": "interactive",
            "conversation_id": "conv-1",
        }
        mock_log.error.assert_called_once()
        assert "Error when calling agent" in mock_log.error.call_args.args[0]
        assert mock_log.error.call_args.kwargs["error_type"] == "RuntimeError"
        assert mock_log.error.call_args.kwargs["error"] == "boom"

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
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(user_id=None),
            )

        chunks = [chunk async for chunk in gen]
        assert len(chunks) == 1
        _no_real_analytics.assert_not_called()


# ---------------------------------------------------------------------------
# call_agent_silent
# ---------------------------------------------------------------------------


class TestCallAgentSilent:
    """Tests for call_agent_silent (background mode)."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_result(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("Hello!", {"tool": "data"}),
            ),
        ):
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert result == ("Hello!", {"tool": "data"})

    @pytest.mark.asyncio
    async def test_a_graph_failure_propagates_instead_of_becoming_a_result_string(self):
        """A swallowed failure returned as a normal result reads as success to every
        caller — which is how workflows reported success through the Gemini 429s."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("429 Too Many Requests"),
            ),
            pytest.raises(RuntimeError, match="429 Too Many Requests"),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

    @pytest.mark.asyncio
    async def test_passes_trigger_context_to_core(self):
        trigger = {"type": "cron", "schedule": "daily"}
        patches = _common_patches()
        with (
            patches["construct"] as mock_construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("ok", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context=trigger,
            )

        # construct_langchain_messages should get trigger_context
        assert mock_construct.call_args.kwargs["trigger_context"] == trigger

    @pytest.mark.asyncio
    async def test_usage_metadata_logging(self):
        """When usage_metadata_callback has data, it should be logged."""
        callback = MagicMock()
        callback.usage_metadata = {
            "model_a": {"input_tokens": 100, "output_tokens": 50},
            "model_b": {"input_tokens": 200, "output_tokens": 75},
        }

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                usage_metadata_callback=callback,
            )

        # log.set should be called with token counts
        log_calls = mock_log.set.call_args_list
        # Find the call with token_input
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call is not None
        assert token_call.kwargs["token_input"] == 300  # 100 + 200
        assert token_call.kwargs["token_output"] == 125  # 50 + 75
        assert token_call.kwargs["token_total"] == 425
        # Which model spent those tokens — the counts are unattributable without it.
        assert token_call.kwargs["agent"] == {"model": "gpt-4o"}

    @pytest.mark.asyncio
    async def test_usage_metadata_with_none_metadata(self):
        """When usage_metadata is None, token totals should be zero."""
        callback = MagicMock()
        callback.usage_metadata = None

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                usage_metadata_callback=callback,
            )

        # usage_metadata is None -> or {} -> sums are 0
        log_calls = mock_log.set.call_args_list
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call is not None
        assert token_call.kwargs["token_input"] == 0
        assert token_call.kwargs["token_output"] == 0
        assert token_call.kwargs["token_total"] == 0

    @pytest.mark.asyncio
    async def test_usage_metadata_no_callback(self):
        """Without a callback, no usage logging should happen."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        log_calls = mock_log.set.call_args_list
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call is None

    @pytest.mark.asyncio
    async def test_usage_metadata_with_mixed_values(self):
        """usage_metadata may contain non-dict values; those should be skipped."""
        callback = MagicMock()
        callback.usage_metadata = {
            "model_a": {"input_tokens": 10, "output_tokens": 5},
            "total": 15,  # not a dict — should be ignored
        }

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                usage_metadata_callback=callback,
            )

        log_calls = mock_log.set.call_args_list
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call is not None
        assert token_call.kwargs["token_input"] == 10
        assert token_call.kwargs["token_output"] == 5

    @pytest.mark.asyncio
    async def test_a_message_construction_failure_propagates(self):
        """Every seam inside call_agent_silent propagates, not just the graph run."""
        patches = _common_patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("silent boom"),
            ),
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            pytest.raises(RuntimeError, match="silent boom"),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

    @pytest.mark.asyncio
    async def test_run_lifecycle_events_captured(self, _no_real_analytics):
        """STARTED before the silent run, COMPLETED after it succeeds."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("Hello!", {"tool": "data"}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [
            AnalyticsEvents.AGENT_RUN_STARTED,
            AnalyticsEvents.AGENT_RUN_COMPLETED,
        ]
        started = _no_real_analytics.call_args_list[0]
        assert started.args[0] == "user-123"
        assert started.args[2] == {
            "agent": "comms",
            "mode": "background",
            "conversation_id": "conv-1",
        }
        completed = _no_real_analytics.call_args_list[1]
        assert completed.args[0] == "user-123"
        assert completed.args[2] == {
            "agent": "comms",
            "mode": "background",
            "conversation_id": "conv-1",
        }

    @pytest.mark.asyncio
    async def test_execute_failure_captures_failed(self, _no_real_analytics):
        """execute_graph_silent raising propagates and captures FAILED."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("execute failed"),
            ),
            patch("app.agents.core.agent.teardown_executor_capture") as mock_teardown,
            pytest.raises(RuntimeError, match="execute failed"),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        events = [c.args[1] for c in _no_real_analytics.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_STARTED, AnalyticsEvents.AGENT_RUN_FAILED]
        failed = _no_real_analytics.call_args_list[1]
        assert failed.args[0] == "user-123"
        assert failed.args[2] == {
            "agent": "comms",
            "mode": "background",
            "conversation_id": "conv-1",
        }
        mock_log.error.assert_called_once()
        assert "Error when calling silent agent" in mock_log.error.call_args.args[0]
        assert mock_log.error.call_args.kwargs["error_type"] == "RuntimeError"
        assert mock_log.error.call_args.kwargs["error"] == "execute failed"
        mock_teardown.assert_called_once()
        assert UUID(mock_teardown.call_args.args[0])

    @pytest.mark.asyncio
    async def test_missing_user_id_skips_events(self, _no_real_analytics):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("Hello!", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(user_id=None),
            )

        _no_real_analytics.assert_not_called()


# ---------------------------------------------------------------------------
# the lane the top-level run resolves
# ---------------------------------------------------------------------------


def _fresh_config() -> dict:
    """A config object this test owns.

    ``_core_agent_logic`` MUTATES ``config["configurable"]``, so the shared
    module-level FAKE_CONFIG cannot be used by anything that asserts on those
    writes — one test would see the previous test's key.
    """
    return {"configurable": {"thread_id": "conv-1", "user_id": "user-123", "model": "gpt-4o"}}


class TestTheLaneTheRunResolves:
    """This is the top-level run: ``build_agent_config`` resolves the comms lane
    here and the executor plus every subagent inherit it whole. Everything the run
    is has to reach that one call — a blanked or dropped argument is a turn that
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
            # in CI (no .env) and fails on every developer machine, where
            # apps/api/.env sets ENV=development and the dev selector resolves an
            # option. Pinned the same way TestTheDevModelSelector pins it.
            patch.object(agent_module.settings, "ENV", "production"),
            patch(
                "app.agents.core.agent.build_agent_config",
                new_callable=AsyncMock,
                return_value=_fresh_config(),
            ) as build_config,
            patches["log"],
            # Pinned, as the dev-selector classes below already do: the dev model
            # menu is live only in development, and a developer's own .env sets
            # ENV=development — so an unpinned run resolves DEV_DEFAULT_MODEL and
            # this expectation holds in CI and nowhere else.
            patch.object(agent_module.settings, "ENV", "production"),
        ):
            await _core_agent_logic(
                request=request,
                conversation_id="conv-1",
                user=user,
                usage_metadata_callback=callback,
                source="web",
                langfuse_trace_id="trace-1",
                langfuse_tags=["tag-a"],
            )

        assert build_config.call_args.args == ()
        assert build_config.call_args.kwargs == {
            "conversation_id": "conv-1",
            "user": user,
            "role": AgentRole.COMMS,
            "dev_option": None,
            "usage_metadata_callback": callback,
            "agent_name": "comms_agent",
            "selected_tool": "web_search",
            "tool_category": "research",
            "active_todo_id": None,
            "execution_mode": "interactive",
            "source": "web",
            "user_messages": recent_user_messages(request.messages, request.message),
            "user_request": request.message,
            "user_preferences": None,
            "writing_style": None,
            "langfuse_trace_id": "trace-1",
            "langfuse_tags": ["tag-a"],
        }

    @pytest.mark.asyncio
    async def test_a_background_trigger_run_says_so(self):
        """The mode and the todo come from the trigger context, and the executor
        inherits both — a wrong value here routes the result to the wrong place."""
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
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"execution_mode": "background", "todo_id": "todo-9"},
            )

        assert build_config.call_args.kwargs["execution_mode"] == "background"
        assert build_config.call_args.kwargs["active_todo_id"] == "todo-9"


class TestTheDevModelSelector:
    """DEV-ONLY: the chat-header model picker. It wins over plan routing inside
    resolve_lane, and must be inert in production."""

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
            patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", dev_default),
        ):
            await _core_agent_logic(request=request, conversation_id="conv-1", user=_make_user())
        return build_config.call_args.kwargs["dev_option"]

    @pytest.mark.asyncio
    async def test_an_explicit_comms_pick_becomes_the_runs_dev_option(self):
        option = await self._dev_option_for(
            _make_request(comms_model="minimax-m3", use_default_models=False)
        )

        assert option == DEV_MODEL_OPTIONS["minimax-m3"]

    @pytest.mark.asyncio
    async def test_expressing_no_preference_takes_the_env_configured_default(self):
        """``use_default_models`` is what routes bots, scripts and plain requests
        onto the dev model too, so it cannot be ignored here."""
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
    """The executor builds its own configurable and would otherwise inherit
    comms's lane, so its dev pick rides down on the configurable for
    prepare_executor_execution to resolve."""

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
            patch.object(lane_module.settings, "DEV_DEFAULT_MODEL", dev_default),
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
