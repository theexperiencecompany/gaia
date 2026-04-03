"""Unit tests for app.agents.core.agent — call_agent and call_agent_silent."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.core.agent import (
    _core_agent_logic,
    call_agent,
    call_agent_silent,
)
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
        "store_mem": patch(
            "app.agents.core.agent.store_user_message_memory",
            new_callable=AsyncMock,
        ),
        "log": patch("app.agents.core.agent.log"),
    }


# ---------------------------------------------------------------------------
# _core_agent_logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
            patches["store_mem"],
            patches["log"],
        ):
            graph, state, config = await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=user,
                user_time=datetime.now(timezone.utc),
            )

        mock_construct.assert_awaited_once()
        kwargs = mock_construct.call_args.kwargs
        assert kwargs["query"] == "custom query"
        assert kwargs["user_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_fires_background_memory_task(self):
        """When user_id and message are present, a background task is created."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["store_mem"] as mock_store,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(message="remember this"),
                conversation_id="conv-1",
                user=_make_user(user_id="uid-1"),
                user_time=datetime.now(timezone.utc),
            )

            # Give the event loop a tick so the background task fires
            await asyncio.sleep(0)

        mock_store.assert_awaited_once_with("uid-1", "remember this", "conv-1")

    @pytest.mark.asyncio
    async def test_skips_memory_when_no_user_id(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["store_mem"] as mock_store,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(user_id=None),
                user_time=datetime.now(timezone.utc),
            )

            await asyncio.sleep(0)

        mock_store.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_memory_when_no_message(self):
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["store_mem"] as mock_store,
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(message=""),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
            )

            await asyncio.sleep(0)

        mock_store.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_trigger_context(self):
        patches = _common_patches()
        trigger = {"type": "gmail", "email_data": {}}
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"] as mock_build_state,
            patches["build_config"],
            patches["store_mem"],
            patches["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
            patches["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
            )

        mock_log.set.assert_called_once()
        call_kwargs = mock_log.set.call_args.kwargs
        assert "agent" in call_kwargs
        assert call_kwargs["agent"]["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# call_agent (streaming)
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
            )

            passed_config = mock_exec.call_args[0][2]
            assert "stream_id" not in passed_config["configurable"]

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
            patches["store_mem"],
            patches["log"],
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
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
            patch("app.agents.core.agent.build_agent_config", return_value=FAKE_CONFIG),
            patch(
                "app.agents.core.agent.store_user_message_memory",
                new_callable=AsyncMock,
            ),
            patch("app.agents.core.agent.log"),
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
            )

        chunks = [chunk async for chunk in gen]
        # Each chunk should end with \n\n (SSE format)
        for chunk in chunks:
            assert chunk.endswith("\n\n")


# ---------------------------------------------------------------------------
# call_agent_silent
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
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
                user_time=datetime.now(timezone.utc),
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
            patches["store_mem"],
            patches["log"],
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(timezone.utc),
            )

        assert "silent boom" in msg
        assert data == {}

    @pytest.mark.asyncio
    async def test_error_in_execute_returns_error_tuple(self):
        """When execute_graph_silent raises, we get an error tuple."""
        patches = _common_patches()
        with (
            patches["construct"],
            patches["get_graph"],
            patches["build_state"],
            patches["build_config"],
            patches["store_mem"],
            patches["log"],
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
                user_time=datetime.now(timezone.utc),
            )

        assert "execute failed" in msg
        assert data == {}
