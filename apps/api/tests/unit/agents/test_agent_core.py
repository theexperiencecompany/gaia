"""Unit tests for app.agents.core.agent — _core_agent_logic, call_agent, call_agent_silent."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core.agent import (
    _core_agent_logic,
    call_agent,
    call_agent_silent,
)
from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory

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
    return MessageRequestWithHistory(**defaults)  # type: ignore[arg-type]


def _make_user(**overrides) -> dict:
    defaults = {
        "user_id": "user-123",
        "email": "test@example.com",
        "name": "Test User",
    }
    defaults.update(overrides)
    return defaults


def _make_config(**configurable_overrides) -> dict:
    """A fresh config bag per call — tests that mutate configurable share nothing."""
    configurable = {
        "thread_id": "conv-1",
        "user_id": "user-123",
        "model_name": "gpt-4o",
    }
    configurable.update(configurable_overrides)
    return {"configurable": configurable}


class _FakeSettings:
    """Stub for app.agents.core.agent.settings; only ENV is read."""

    def __init__(self, env: str) -> None:
        self.ENV = env


class _UsageCallback:
    """Real object with a usage_metadata attribute.

    MagicMock would auto-create ANY attribute name on access, so hasattr-based
    mutants (attribute name typos) could never be told apart — the fake must
    be a real object.
    """

    def __init__(self, metadata) -> None:
        self.usage_metadata = metadata


def _fake_stream(*chunks: str):
    """Async generator fake for execute_graph_streaming."""

    async def _gen(*args, **kwargs):
        for chunk in chunks:
            yield chunk

    return _gen()


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
        "model_name": "gpt-4o",
    }
}

UUID4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


# ---------------------------------------------------------------------------
# Patches common to most tests
# ---------------------------------------------------------------------------


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
        "build_config": patch(
            "app.agents.core.agent.build_agent_config",
            return_value=FAKE_CONFIG,
        ),
        "apply_plan": patch(
            "app.agents.core.agent.apply_plan_model",
            new_callable=AsyncMock,
        ),
        # The dev-only model override runs after apply_plan_model and would
        # otherwise pop model_name off the shared FAKE_CONFIG when
        # use_default_models=True (the request default) with a DEV_DEFAULT_MODEL
        # entry configured — polluting every later test in this module.
        "apply_dev_model": patch(
            "app.agents.core.agent.apply_dev_model_override",
        ),
        "log": patch("app.agents.core.agent.log"),
    }


def _silent_flow_patches():
    """Executor-capture seams for call_agent_silent, returned as mocks."""
    return {
        "register": patch("app.agents.core.agent.register_executor_capture"),
        "await_done": patch(
            "app.agents.core.agent.await_executor_done", new_callable=AsyncMock
        ),
        "drain": patch(
            "app.agents.core.agent.drain_executor_tool_data", return_value=[]
        ),
        "teardown": patch("app.agents.core.agent.teardown_executor_capture"),
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
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_construct_messages_receives_all_args(self):
        req = _make_request(
            message="custom query",
            messages=[{"role": "user", "content": "hello"}],
            fileIds=["f-1"],
            fileData=[{"fileId": "f-1", "url": "http://x", "filename": "a.pdf"}],
            selectedTool="gmail",
            toolCategory="email",
            selectedWorkflow={
                "id": "wf-1",
                "title": "Triage",
                "description": "D",
                "steps": [],
            },
            selectedCalendarEvent={
                "id": "ev-1",
                "summary": "Standup",
                "description": "D",
                "start": {},
                "end": {},
            },
            replyToMessage={"id": "m-9", "content": "c", "role": "user"},
        )
        user = _make_user(name="Alice")
        trigger = {"type": "cron", "active_todo_id": "todo-1"}
        patches = _common_patches()
        with (
            patches["construct"] as mock_construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=user,
                trigger_context=trigger,
                source="workflow",
            )

        mock_construct.assert_awaited_once()
        kwargs = mock_construct.call_args.kwargs
        assert kwargs["messages"] is req.messages
        assert kwargs["files_data"] is req.fileData
        assert kwargs["currently_uploaded_file_ids"] is req.fileIds
        assert kwargs["user_id"] == "user-123"
        assert kwargs["query"] == "custom query"
        assert kwargs["user_name"] == "Alice"
        assert kwargs["user_dict"] is user
        assert kwargs["selected_tool"] is req.selectedTool
        assert kwargs["tool_category"] is req.toolCategory
        assert kwargs["selected_workflow"] is req.selectedWorkflow
        assert kwargs["selected_calendar_event"] is req.selectedCalendarEvent
        assert kwargs["reply_to_message"] is req.replyToMessage
        assert kwargs["trigger_context"] is trigger
        assert kwargs["active_todo_id"] == "todo-1"
        assert kwargs["execution_mode"] == "interactive"
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["source"] == "workflow"

    @pytest.mark.asyncio
    async def test_get_graph_called_with_comms_agent(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"] as mock_get_graph,
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_get_graph.assert_awaited_once_with("comms_agent")

    @pytest.mark.asyncio
    async def test_build_initial_state_receives_exact_args(self):
        req = _make_request()
        trigger = {"type": "gmail", "email_data": {}}
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"] as mock_build_state,
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context=trigger,
            )

        args = mock_build_state.call_args.args
        assert args[0] is req
        assert args[1] == "user-123"
        assert args[2] == "conv-1"
        assert args[3] is FAKE_HISTORY
        assert args[4] is trigger

    @pytest.mark.asyncio
    async def test_build_initial_state_user_id_fallback_to_empty(self):
        user = _make_user()
        del user["user_id"]
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"] as mock_build_state,
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=user,
            )

        assert mock_build_state.call_args.args[1] == ""

    @pytest.mark.asyncio
    async def test_build_agent_config_receives_all_args(self):
        req = _make_request(selectedTool="gmail", toolCategory="email")
        user = _make_user()
        callback = MagicMock(name="usage_callback")
        model_config = MagicMock(name="model_config")
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.recent_user_messages",
                return_value=["latest turn"],
            ) as mock_recent,
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=user,
                user_model_config=model_config,
                usage_metadata_callback=callback,
                trigger_context={"active_todo_id": "todo-1", "execution_mode": "background"},
                source="test-src",
                langfuse_trace_id="trace-1",
                langfuse_tags=["tag-a"],
            )

        mock_recent.assert_called_once_with(req.messages, req.message)
        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["user"] is user
        assert kwargs["user_model_config"] is model_config
        assert kwargs["usage_metadata_callback"] is callback
        assert kwargs["agent_name"] == "comms_agent"
        assert kwargs["selected_tool"] == "gmail"
        assert kwargs["tool_category"] == "email"
        assert kwargs["active_todo_id"] == "todo-1"
        assert kwargs["execution_mode"] == "background"
        assert kwargs["source"] == "test-src"
        assert kwargs["user_messages"] == ["latest turn"]
        assert kwargs["langfuse_trace_id"] == "trace-1"
        assert kwargs["langfuse_tags"] == ["tag-a"]

    @pytest.mark.asyncio
    async def test_apply_plan_model_called_with_configurable_and_user_id(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"] as mock_apply_plan,
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_apply_plan.assert_awaited_once_with(config["configurable"], "user-123")

    @pytest.mark.asyncio
    async def test_dev_model_override_applied_in_development(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"] as mock_dev,
            patches["log"],
            patch("app.agents.core.agent.settings", _FakeSettings(env="development")),
        ):
            await _core_agent_logic(
                request=_make_request(
                    comms_model="cm-1", executor_model="em-1", use_default_models=False
                ),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_dev.assert_called_once()
        assert mock_dev.call_args.args[0] is config["configurable"]
        dev_kwargs = mock_dev.call_args.kwargs
        assert dev_kwargs["comms_model"] == "cm-1"
        assert dev_kwargs["executor_model"] == "em-1"
        assert dev_kwargs["use_defaults"] is False

    @pytest.mark.asyncio
    async def test_dev_model_override_skipped_in_production(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"] as mock_dev,
            patches["log"],
            patch("app.agents.core.agent.settings", _FakeSettings(env="production")),
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_dev.assert_not_called()

    @pytest.mark.asyncio
    async def test_execution_mode_background_with_todo_fallback(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"todo_id": "todo-2", "execution_mode": "background"},
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["active_todo_id"] == "todo-2"
        assert kwargs["execution_mode"] == "background"

    @pytest.mark.asyncio
    async def test_case_variant_execution_mode_falls_back_to_interactive(self):
        """Only the exact lowercase spellings are honored."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"execution_mode": "INTERACTIVE"},
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["execution_mode"] == "interactive"

    @pytest.mark.asyncio
    async def test_execution_mode_defaults_to_interactive_without_trigger(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["active_todo_id"] is None
        assert kwargs["execution_mode"] == "interactive"

    @pytest.mark.asyncio
    async def test_invalid_execution_mode_stays_interactive(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"execution_mode": "scheduled", "active_todo_id": ""},
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["active_todo_id"] is None
        assert kwargs["execution_mode"] == "interactive"

    @pytest.mark.asyncio
    async def test_workflow_trigger_populates_configurable_with_defaults(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"workflow_id": "wf-1"},
            )

        assert config["configurable"]["workflow_id"] == "wf-1"
        assert config["configurable"]["workflow_title"] == ""
        assert config["configurable"]["workflow_notify_on_completion"] is True

    @pytest.mark.asyncio
    async def test_workflow_trigger_populates_configurable_explicit(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={
                    "workflow_id": "wf-1",
                    "workflow_title": "Morning brief",
                    "workflow_notify_on_completion": False,
                },
            )

        assert config["configurable"]["workflow_id"] == "wf-1"
        assert config["configurable"]["workflow_title"] == "Morning brief"
        assert config["configurable"]["workflow_notify_on_completion"] is False

    @pytest.mark.asyncio
    async def test_no_workflow_keys_without_workflow_id(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"type": "cron"},
            )

        assert "workflow_id" not in config["configurable"]
        assert "workflow_title" not in config["configurable"]
        assert "workflow_notify_on_completion" not in config["configurable"]

    @pytest.mark.asyncio
    async def test_log_set_full_agent_metadata(self):
        req = _make_request(
            selectedWorkflow={
                "id": "wf-1",
                "title": "Triage",
                "description": "D",
                "steps": [],
            },
            selectedCalendarEvent={
                "id": "ev-1",
                "summary": "Standup",
                "description": "D",
                "start": {},
                "end": {},
            },
            replyToMessage={"id": "m-9", "content": "c", "role": "user"},
        )
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=_make_user(),
                trigger_context={"type": "cron"},
            )

        mock_log.set.assert_called_once()
        assert mock_log.set.call_args.kwargs["agent"] == {
            "model": "gpt-4o",
            "has_workflow": True,
            "has_trigger_context": True,
            "has_calendar_event": True,
            "has_reply": True,
            "history_message_count": 2,
        }

    @pytest.mark.asyncio
    async def test_error_propagates_when_construct_fails(self):
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
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await _core_agent_logic(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )


# ---------------------------------------------------------------------------
# call_agent (streaming)
# ---------------------------------------------------------------------------


class TestCallAgent:
    """Tests for call_agent (streaming mode)."""

    @pytest.mark.asyncio
    async def test_returns_streaming_generator(self):
        """Happy path: returns the generator from execute_graph_streaming."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: {}\n\n", "data: [DONE]\n\n"),
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
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                stream_id="stream-abc",
            )

            passed_config = mock_exec.call_args.args[2]
            assert passed_config["configurable"]["stream_id"] == "stream-abc"

    @pytest.mark.asyncio
    async def test_no_stream_id_when_not_provided(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                return_value=_make_config(),
            ),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

            passed_config = mock_exec.call_args.args[2]
            assert "stream_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_falsy_stream_id_not_added(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                stream_id="",
            )

            passed_config = mock_exec.call_args.args[2]
            assert passed_config is config
            assert "stream_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_user_message_id_added_to_config(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_message_id="um-1",
            )

            passed_config = mock_exec.call_args.args[2]
            assert passed_config["configurable"]["user_message_id"] == "um-1"

    @pytest.mark.asyncio
    async def test_execute_streaming_receives_exact_objects(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args == (FAKE_GRAPH, FAKE_STATE, config)

    @pytest.mark.asyncio
    async def test_forwards_model_config_callback_and_source(self):
        callback = MagicMock(name="usage_callback")
        model_config = MagicMock(name="model_config")
        user = _make_user()
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config", return_value=config
            ) as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ),
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-2",
                user=user,
                user_model_config=model_config,
                usage_metadata_callback=callback,
                source="bot-src",
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["conversation_id"] == "conv-2"
        assert kwargs["user"] is user
        assert kwargs["user_model_config"] is model_config
        assert kwargs["usage_metadata_callback"] is callback
        assert kwargs["source"] == "bot-src"

    @pytest.mark.asyncio
    async def test_langfuse_trace_id_forwarded_from_bot_message_id(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config)
            as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.trace_id_for_message", return_value="trace-seeded"
            ) as mock_trace,
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ),
            patch("app.agents.core.agent.settings", _FakeSettings(env="development")),
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                bot_message_id="bot-42",
            )

        mock_trace.assert_called_once_with("bot-42")
        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["langfuse_trace_id"] == "trace-seeded"
        assert kwargs["langfuse_tags"] == ["comms_agent", "development"]

    @pytest.mark.asyncio
    async def test_no_trace_id_without_bot_message_id(self):
        config = _make_config()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config)
            as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.trace_id_for_message", return_value="trace-seeded"
            ) as mock_trace,
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream("data: [DONE]\n\n"),
            ),
            patch("app.agents.core.agent.settings", _FakeSettings(env="production")),
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_trace.assert_not_called()
        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["langfuse_trace_id"] is None
        assert kwargs["langfuse_tags"] == ["comms_agent", "production"]

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
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_error_yields_exact_sse_frames_and_logs(self):
        """Error path: exact SSE frames, log.error with type and message."""
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
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"] as mock_log,
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        chunks = [chunk async for chunk in gen]
        assert chunks == [
            'data: {"error": "Error when calling agent: boom"}\n\n',
            "data: [DONE]\n\n",
        ]
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == (
            f"{LogTag.AGENT} Error when calling agent"
        )
        err_kwargs = mock_log.error.call_args.kwargs
        assert err_kwargs["error_type"] == "RuntimeError"
        assert err_kwargs["error"] == "boom"

    @pytest.mark.asyncio
    async def test_execute_streaming_raises_returns_error_generator(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                side_effect=RuntimeError("stream broke"),
            ),
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        chunks = [chunk async for chunk in gen]
        assert chunks == [
            'data: {"error": "Error when calling agent: stream broke"}\n\n',
            "data: [DONE]\n\n",
        ]

    @pytest.mark.asyncio
    async def test_base_exception_not_swallowed(self):
        """The error handler catches Exception, not BaseException."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch(
                "app.agents.core.agent.build_agent_config",
                side_effect=KeyboardInterrupt(),
            ),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
        ):
            with pytest.raises(KeyboardInterrupt):
                await call_agent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )


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
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_passes_trigger_context_to_core(self):
        trigger = {"type": "cron", "schedule": "daily"}
        patches = _common_patches()
        with (
            patches["construct"] as mock_construct,
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_forwards_model_config_callback_and_source(self):
        callback = MagicMock(name="usage_callback")
        model_config = MagicMock(name="model_config")
        user = _make_user()
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"] as mock_build_config,
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("ok", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-2",
                user=user,
                usage_metadata_callback=callback,
                user_model_config=model_config,
                source="workflow",
            )

        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["conversation_id"] == "conv-2"
        assert kwargs["user"] is user
        assert kwargs["user_model_config"] is model_config
        assert kwargs["usage_metadata_callback"] is callback
        assert kwargs["source"] == "workflow"

    @pytest.mark.asyncio
    async def test_stream_id_uuid_registered_and_forwarded(self):
        config = _make_config()
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patch("app.agents.core.agent.build_agent_config", return_value=config),
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"] as mock_register,
            silent["await_done"],
            silent["drain"],
            silent["teardown"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("ok", {}),
            ) as mock_exec,
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        mock_register.assert_called_once()
        stream_id = mock_register.call_args.args[0]
        assert UUID4_RE.fullmatch(stream_id)
        assert uuid.UUID(stream_id).version == 4
        mock_exec.assert_awaited_once()
        assert mock_exec.call_args.args == (FAKE_GRAPH, FAKE_STATE, config)
        passed_config = mock_exec.call_args.args[2]
        assert passed_config["configurable"]["stream_id"] == stream_id

    @pytest.mark.asyncio
    async def test_executor_capture_lifecycle(self):
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"] as mock_register,
            silent["await_done"] as mock_await_done,
            silent["drain"] as mock_drain,
            silent["teardown"] as mock_teardown,
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
            )

        stream_id = mock_register.call_args.args[0]
        mock_await_done.assert_awaited_once_with(stream_id)
        mock_drain.assert_called_once_with(stream_id)
        mock_teardown.assert_called_once_with(stream_id)

    @pytest.mark.asyncio
    async def test_merges_executor_tool_data(self):
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"],
            silent["await_done"],
            silent["drain"] as mock_drain,
            silent["teardown"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("resp", {"tool_data": [{"tool_name": "a"}]}),
            ),
        ):
            mock_drain.return_value = [{"tool_name": "b"}]
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert result == ("resp", {"tool_data": [{"tool_name": "a"}, {"tool_name": "b"}]})

    @pytest.mark.asyncio
    async def test_merges_executor_tool_data_creates_key(self):
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"],
            silent["await_done"],
            silent["drain"] as mock_drain,
            silent["teardown"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("resp", {"other": 1}),
            ),
        ):
            mock_drain.return_value = [{"tool_name": "b"}]
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert result == ("resp", {"other": 1, "tool_data": [{"tool_name": "b"}]})

    @pytest.mark.asyncio
    async def test_skips_merge_when_no_executor_data(self):
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"],
            silent["await_done"],
            silent["drain"] as mock_drain,
            silent["teardown"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("resp", {"other": 1}),
            ),
        ):
            mock_drain.return_value = []
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert result == ("resp", {"other": 1})
        assert "tool_data" not in result[1]

    @pytest.mark.asyncio
    async def test_usage_metadata_logging(self):
        """When usage_metadata_callback has data, it should be logged."""
        callback = _UsageCallback(
            {
                "model_a": {"input_tokens": 100, "output_tokens": 50},
                "model_b": {"input_tokens": 200, "output_tokens": 75},
            }
        )

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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

    @pytest.mark.asyncio
    async def test_usage_metadata_logs_model_from_config(self):
        """The usage log line carries the plan-routed model name."""
        callback = _UsageCallback({"model_a": {"input_tokens": 10, "output_tokens": 5}})

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
        assert token_call.kwargs["agent"] == {"model": "gpt-4o"}
        assert token_call.kwargs["token_input"] == 10
        assert token_call.kwargs["token_output"] == 5
        assert token_call.kwargs["token_total"] == 15

    @pytest.mark.asyncio
    async def test_usage_metadata_with_none_metadata(self):
        """When usage_metadata is None, token totals should be zero."""
        callback = _UsageCallback(None)

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_usage_metadata_defaults_missing_token_keys(self):
        """A model with only input_tokens counts 0 output tokens."""
        callback = _UsageCallback({"model_a": {"input_tokens": 7}})

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
        assert token_call.kwargs["token_input"] == 7
        assert token_call.kwargs["token_output"] == 0
        assert token_call.kwargs["token_total"] == 7

    @pytest.mark.asyncio
    async def test_usage_metadata_missing_input_tokens_defaults_to_zero(self):
        """A model missing input_tokens counts 0 input tokens."""
        callback = _UsageCallback({"model_a": {"output_tokens": 3}})

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                usage_metadata_callback=callback,
            )

        assert result == ("response", {})
        log_calls = mock_log.set.call_args_list
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call.kwargs["token_input"] == 0
        assert token_call.kwargs["token_output"] == 3
        assert token_call.kwargs["token_total"] == 3

    @pytest.mark.asyncio
    async def test_usage_metadata_no_callback(self):
        """Without a callback, no usage logging should happen."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_usage_metadata_callback_without_attribute(self):
        """A callback object lacking usage_metadata skips usage logging entirely."""
        callback = object()

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"] as mock_log,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                usage_metadata_callback=callback,
            )

        assert result == ("response", {})
        log_calls = mock_log.set.call_args_list
        token_call = next((c for c in log_calls if "token_input" in c.kwargs), None)
        assert token_call is None

    @pytest.mark.asyncio
    async def test_usage_metadata_with_mixed_values(self):
        """usage_metadata may contain non-dict values; those should be skipped."""
        callback = _UsageCallback(
            {
                "model_a": {"input_tokens": 10, "output_tokens": 5},
                "total": 15,  # not a dict — should be ignored
            }
        )

        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
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
    async def test_error_returns_error_tuple(self):
        """On exception, call_agent_silent returns an error message and empty dict."""
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
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"] as mock_log,
            _silent_flow_patches()["teardown"] as mock_teardown,
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert msg == "Error when calling silent agent: silent boom"
        assert data == {}
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == (
            f"{LogTag.AGENT} Error when calling silent agent"
        )
        err_kwargs = mock_log.error.call_args.kwargs
        assert err_kwargs["error_type"] == "RuntimeError"
        assert err_kwargs["error"] == "silent boom"
        mock_teardown.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_in_execute_returns_error_tuple(self):
        """When execute_graph_silent raises, we get an error tuple."""
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"] as mock_register,
            silent["teardown"] as mock_teardown,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("execute failed"),
            ),
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
            )

        assert msg == "Error when calling silent agent: execute failed"
        assert data == {}
        # teardown runs in finally even when execution failed mid-flow
        mock_register.assert_called_once()
        stream_id = mock_register.call_args.args[0]
        mock_teardown.assert_called_once_with(stream_id)

    @pytest.mark.asyncio
    async def test_base_exception_not_swallowed(self):
        """The error handler catches Exception, not BaseException; teardown still runs."""
        patches = _common_patches()
        silent = _silent_flow_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["apply_plan"],
            patches["apply_dev_model"],
            patches["log"],
            silent["register"] as mock_register,
            silent["teardown"] as mock_teardown,
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                side_effect=KeyboardInterrupt(),
            ),
        ):
            with pytest.raises(KeyboardInterrupt):
                await call_agent_silent(
                    request=_make_request(),
                    conversation_id="conv-1",
                    user=_make_user(),
                )

        mock_register.assert_called_once()
        stream_id = mock_register.call_args.args[0]
        mock_teardown.assert_called_once_with(stream_id)
