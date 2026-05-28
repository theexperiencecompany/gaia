"""Unit tests for app.agents.core.agent.

UNIT: app/agents/core/agent.py :: _core_agent_logic, call_agent, call_agent_silent

EXPECTED
  _core_agent_logic: shared setup. Resolves active_todo_id + execution_mode from
    trigger_context, fans out construct_langchain_messages + GraphManager.get_graph
    concurrently, builds initial_state and config, fires a fire-and-forget memory
    task when (user_id AND message), records a wide-event agent summary, and returns
    (graph, initial_state, config).
  call_agent: streaming front door. Seeds a Langfuse trace_id from bot_message_id,
    tags the run ["comms_agent", settings.ENV], injects stream_id / user_message_id
    into config["configurable"] only when supplied, and returns the
    execute_graph_streaming generator. On ANY setup error it instead returns an
    error generator yielding one error SSE frame then "data: [DONE]\n\n".
  call_agent_silent: background front door. Runs execute_graph_silent, sums
    per-model usage tokens onto the wide event when a usage callback carries
    metadata, and returns the (message, tool_data) tuple. On ANY error it returns
    ("Error when calling silent agent: <exc>", {}).

MECHANISM
  trigger_context.get("active_todo_id") or .get("todo_id"); execution_mode only
  accepted if in ("interactive","background"); asyncio.gather(construct, get_graph);
  build_initial_state(request, user_id or "", conversation_id, history, trigger_context);
  build_agent_config(... active_todo_id=, execution_mode=, langfuse_trace_id=, langfuse_tags=);
  fire-and-forget task tracked in _background_tasks; log.set(agent={...}); return triple.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - get_graph is called with the literal "comms_agent", not another agent name   [graph contract]
  - active_todo_id resolves from "active_todo_id" first, falling back to "todo_id" [trigger binding]
  - execution_mode is taken from trigger_context only when in the allowed set,
    otherwise stays "interactive"                                                 [mode whitelist]
  - the resolved active_todo_id / execution_mode reach BOTH build_initial_state
    (via trigger_context arg) and build_agent_config (via kwargs)                  [propagation]
  - the background memory task runs with (user_id, message, conversation_id) only
    when both user_id and message are truthy; skipped otherwise                    [fire-and-forget gate]
  - log.set agent dict carries the real model_name, history_message_count, and the
    boolean has_* flags derived from the request/trigger                           [observability contract]
  - call_agent with bot_message_id calls trace_id_for_message(bot_message_id) and
    forwards that trace id + tags ["comms_agent", settings.ENV] into build_agent_config [langfuse seed]
  - call_agent without bot_message_id passes langfuse_trace_id=None                 [no-seed branch]
  - stream_id / user_message_id appear in config["configurable"] only when supplied [config injection]
  - call_agent happy path returns exactly the execute_graph_streaming generator     [return identity]
  - call_agent on setup failure returns an error generator: first frame is a JSON
    SSE carrying the exception text, second is "data: [DONE]\n\n"                    [error SSE contract]
  - call_agent_silent forwards trigger_context positionally to _core_agent_logic    [silent trigger path]
  - call_agent_silent returns exactly what execute_graph_silent returned            [silent return]
  - usage token logging sums input/output across dict-valued entries, ignores
    non-dict entries, treats None metadata as {}, and is skipped without a callback [token math]
  - call_agent_silent on error returns ("Error when calling silent agent: <exc>", {}) [error tuple]

EQUIVALENT MUTANTS (allowed survivors, justified): none expected.
"""

import asyncio
from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core import agent as agent_module
from app.agents.core.agent import (
    _core_agent_logic,
    call_agent,
    call_agent_silent,
)
from app.config.settings import settings
from app.models.message_models import MessageRequestWithHistory

# ---------------------------------------------------------------------------
# Helpers / fixtures
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


# Two-element history so history_message_count assertions can't pass by accident
# against a different list length.
FAKE_HISTORY = [
    SystemMessage(content="You are helpful."),
    HumanMessage(content="Hello agent"),
]
FAKE_GRAPH = MagicMock(name="fake_graph")
FAKE_STATE = {"messages": FAKE_HISTORY, "query": "Hello agent"}


def _config(**configurable_overrides) -> dict:
    """A fresh config dict each call so per-test mutation never leaks."""
    configurable = {
        "thread_id": "conv-1",
        "user_id": "user-123",
        "model_name": "gpt-4o",
    }
    configurable.update(configurable_overrides)
    return {"configurable": configurable}


def _common_patches(*, config: dict | None = None):
    """Patch every I/O boundary of the agent module.

    Boundaries mocked: construct_langchain_messages (LLM/message I/O), the
    GraphManager graph factory, the fire-and-forget memory writer, and the wide
    event logger. build_initial_state / build_agent_config are collaborators in a
    sibling module — patched so we can assert exactly what agent.py forwards into
    them, which is the behaviour under test here.
    """
    return {
        "construct": patch.object(
            agent_module,
            "construct_langchain_messages",
            new_callable=AsyncMock,
            return_value=FAKE_HISTORY,
        ),
        "get_graph": patch.object(
            agent_module.GraphManager,
            "get_graph",
            new_callable=AsyncMock,
            return_value=FAKE_GRAPH,
        ),
        "build_state": patch.object(
            agent_module,
            "build_initial_state",
            return_value=FAKE_STATE,
        ),
        "build_config": patch.object(
            agent_module,
            "build_agent_config",
            return_value=config if config is not None else _config(),
        ),
        "store_mem": patch.object(
            agent_module,
            "store_user_message_memory",
            new_callable=AsyncMock,
        ),
        "log": patch.object(agent_module, "log"),
    }


async def _drain(generator) -> list[str]:
    return [chunk async for chunk in generator]


# ---------------------------------------------------------------------------
# _core_agent_logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCoreAgentLogic:
    async def test_returns_graph_state_config_triple(self):
        cfg = _config()
        p = _common_patches(config=cfg)
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            graph, state, config = await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert graph is FAKE_GRAPH
        assert state is FAKE_STATE
        assert config is cfg

    async def test_graph_requested_for_comms_agent(self):
        """The graph fetched must be the comms_agent graph, no other name."""
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"] as mock_graph,
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        mock_graph.assert_awaited_once_with("comms_agent")

    async def test_construct_messages_receives_request_and_user_fields(self):
        req = _make_request(message="custom query", selectedTool="search")
        user = _make_user(name="Alice", user_id="uid-7")
        p = _common_patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-42",
                user=user,
                user_time=datetime.now(UTC),
            )

        kwargs = mock_construct.call_args.kwargs
        assert kwargs["query"] == "custom query"
        assert kwargs["user_name"] == "Alice"
        assert kwargs["user_id"] == "uid-7"
        assert kwargs["selected_tool"] == "search"
        assert kwargs["conversation_id"] == "conv-42"
        # Interactive default reaches the message constructor.
        assert kwargs["execution_mode"] == "interactive"
        assert kwargs["active_todo_id"] is None

    async def test_active_todo_id_prefers_active_todo_id_key(self):
        """active_todo_id wins over todo_id when both are present."""
        trigger = {"active_todo_id": "todo-primary", "todo_id": "todo-secondary"}
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"] as mock_state,
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_config.call_args.kwargs["active_todo_id"] == "todo-primary"
        # build_initial_state receives the raw trigger_context (5th positional arg).
        assert mock_state.call_args.args[4] is trigger

    async def test_active_todo_id_falls_back_to_todo_id(self):
        """When active_todo_id is absent, todo_id is used."""
        trigger = {"todo_id": "todo-fallback"}
        p = _common_patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_config.call_args.kwargs["active_todo_id"] == "todo-fallback"
        assert mock_construct.call_args.kwargs["active_todo_id"] == "todo-fallback"

    async def test_execution_mode_background_from_trigger(self):
        trigger = {"execution_mode": "background"}
        p = _common_patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_config.call_args.kwargs["execution_mode"] == "background"
        assert mock_construct.call_args.kwargs["execution_mode"] == "background"

    async def test_execution_mode_invalid_value_stays_interactive(self):
        """An out-of-whitelist mode is ignored; mode stays the interactive default."""
        trigger = {"execution_mode": "turbo"}
        p = _common_patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_config.call_args.kwargs["execution_mode"] == "interactive"
        assert mock_construct.call_args.kwargs["execution_mode"] == "interactive"

    async def test_no_trigger_context_yields_interactive_no_todo(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        kwargs = mock_config.call_args.kwargs
        assert kwargs["execution_mode"] == "interactive"
        assert kwargs["active_todo_id"] is None

    async def test_build_initial_state_receives_user_id_and_history(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"] as mock_state,
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-99",
                user=_make_user(user_id="uid-state"),
                user_time=datetime.now(UTC),
            )

        args = mock_state.call_args.args
        assert args[1] == "uid-state"  # user_id
        assert args[2] == "conv-99"  # conversation_id
        assert args[3] is FAKE_HISTORY  # constructed history

    async def test_build_initial_state_user_id_defaults_to_empty_string(self):
        """Missing user_id is coerced to '' (not None) for build_initial_state."""
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"] as mock_state,
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(user_id=None),
                user_time=datetime.now(UTC),
            )

        assert mock_state.call_args.args[1] == ""

    async def test_fires_background_memory_task_with_exact_args(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"] as mock_store,
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(message="remember this"),
                conversation_id="conv-mem",
                user=_make_user(user_id="uid-mem"),
                user_time=datetime.now(UTC),
            )
            # Let the fire-and-forget task run.
            await asyncio.sleep(0)

        mock_store.assert_awaited_once_with("uid-mem", "remember this", "conv-mem")

    async def test_skips_memory_when_no_user_id(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"] as mock_store,
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(message="hi"),
                conversation_id="conv-1",
                user=_make_user(user_id=None),
                user_time=datetime.now(UTC),
            )
            await asyncio.sleep(0)

        mock_store.assert_not_awaited()

    async def test_skips_memory_when_no_message(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"] as mock_store,
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(message=""),
                conversation_id="conv-1",
                user=_make_user(user_id="uid-x"),
                user_time=datetime.now(UTC),
            )
            await asyncio.sleep(0)

        mock_store.assert_not_awaited()

    async def test_log_set_records_agent_summary(self):
        """The wide event captures model, flags and the real history length."""
        req = _make_request(
            message="hi",
            selectedWorkflow={
                "id": "wf-1",
                "title": "Daily",
                "description": "d",
                "steps": [],
            },
            replyToMessage={"id": "m1", "content": "prev", "role": "user"},
        )
        trigger = {"type": "gmail"}
        p = _common_patches(config=_config(model_name="claude-x"))
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=req,
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        agent_meta = mock_log.set.call_args.kwargs["agent"]
        assert agent_meta["model"] == "claude-x"
        assert agent_meta["has_workflow"] is True
        assert agent_meta["has_trigger_context"] is True
        assert agent_meta["has_reply"] is True
        assert agent_meta["has_calendar_event"] is False
        assert agent_meta["history_message_count"] == len(FAKE_HISTORY)


# ---------------------------------------------------------------------------
# call_agent (streaming)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCallAgent:
    async def test_returns_streaming_generator_unchanged(self):
        """Happy path returns exactly the generator from execute_graph_streaming."""

        async def _fake_stream():
            yield "data: chunk\n\n"
            yield "data: [DONE]\n\n"

        sentinel = _fake_stream()
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch.object(agent_module, "execute_graph_streaming", return_value=sentinel),
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert gen is sentinel
        chunks = await _drain(gen)
        assert chunks == ["data: chunk\n\n", "data: [DONE]\n\n"]

    async def test_bot_message_id_seeds_langfuse_trace_and_tags(self):
        """bot_message_id seeds a trace id that is forwarded into build_agent_config."""

        async def _fake_stream():
            yield "data: [DONE]\n\n"

        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
            patch.object(agent_module, "execute_graph_streaming", return_value=_fake_stream()),
            patch.object(
                agent_module, "trace_id_for_message", return_value="trace-from-msg"
            ) as mock_trace,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                bot_message_id="bot-msg-77",
            )

        mock_trace.assert_called_once_with("bot-msg-77")
        cfg_kwargs = mock_config.call_args.kwargs
        assert cfg_kwargs["langfuse_trace_id"] == "trace-from-msg"
        assert cfg_kwargs["langfuse_tags"] == ["comms_agent", settings.ENV]

    async def test_no_bot_message_id_passes_trace_id_none(self):
        async def _fake_stream():
            yield "data: [DONE]\n\n"

        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
            patch.object(agent_module, "execute_graph_streaming", return_value=_fake_stream()),
            patch.object(agent_module, "trace_id_for_message") as mock_trace,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        mock_trace.assert_not_called()
        assert mock_config.call_args.kwargs["langfuse_trace_id"] is None

    async def test_stream_id_and_user_message_id_injected_into_config(self):
        async def _fake_stream():
            yield "data: [DONE]\n\n"

        cfg = _config()
        p = _common_patches(config=cfg)
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch.object(
                agent_module, "execute_graph_streaming", return_value=_fake_stream()
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                stream_id="stream-abc",
                user_message_id="user-msg-9",
            )

        passed_config = mock_exec.call_args.args[2]
        assert passed_config["configurable"]["stream_id"] == "stream-abc"
        assert passed_config["configurable"]["user_message_id"] == "user-msg-9"

    async def test_optional_ids_absent_when_not_supplied(self):
        async def _fake_stream():
            yield "data: [DONE]\n\n"

        cfg = _config()
        p = _common_patches(config=cfg)
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch.object(
                agent_module, "execute_graph_streaming", return_value=_fake_stream()
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        configurable = mock_exec.call_args.args[2]["configurable"]
        assert "stream_id" not in configurable
        assert "user_message_id" not in configurable

    async def test_passes_graph_and_state_to_executor(self):
        """call_agent feeds the graph + state from _core_agent_logic to the executor."""

        async def _fake_stream():
            yield "data: [DONE]\n\n"

        cfg = _config()
        p = _common_patches(config=cfg)
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch.object(
                agent_module, "execute_graph_streaming", return_value=_fake_stream()
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        graph_arg, state_arg, config_arg = mock_exec.call_args.args
        assert graph_arg is FAKE_GRAPH
        assert state_arg is FAKE_STATE
        assert config_arg is cfg

    async def test_setup_error_returns_error_generator(self):
        """When setup raises, call_agent returns an error SSE stream (no exception)."""
        p = _common_patches()
        with (
            patch.object(
                agent_module,
                "construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom-setup"),
            ),
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        chunks = await _drain(gen)
        assert len(chunks) == 2
        first = json.loads(chunks[0].removeprefix("data: ").strip())
        assert first == {"error": "Error when calling agent: boom-setup"}
        assert chunks[0].endswith("\n\n")
        assert chunks[1] == "data: [DONE]\n\n"

    async def test_setup_error_logged(self):
        p = _common_patches()
        with (
            patch.object(
                agent_module,
                "construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=ValueError("bad input"),
            ),
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )
            await _drain(gen)

        mock_log.error.assert_called_once()
        assert "bad input" in mock_log.error.call_args.args[0]


# ---------------------------------------------------------------------------
# call_agent_silent
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCallAgentSilent:
    async def test_returns_execute_result_tuple(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("Hello!", {"tool_data": [{"x": 1}]}),
            ),
        ):
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert result == ("Hello!", {"tool_data": [{"x": 1}]})

    async def test_trigger_context_forwarded_to_core(self):
        """trigger_context reaches construct_langchain_messages via _core_agent_logic."""
        trigger = {"type": "cron", "execution_mode": "background"}
        p = _common_patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_config,
            p["store_mem"],
            p["log"],
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("ok", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_construct.call_args.kwargs["trigger_context"] is trigger
        # The background mode from trigger_context propagates to config.
        assert mock_config.call_args.kwargs["execution_mode"] == "background"

    async def test_usage_tokens_summed_across_dict_entries(self):
        callback = MagicMock()
        callback.usage_metadata = {
            "model_a": {"input_tokens": 100, "output_tokens": 50},
            "model_b": {"input_tokens": 200, "output_tokens": 75},
        }
        p = _common_patches(config=_config(model_name="sum-model"))
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 300
        assert token_call.kwargs["token_output"] == 125
        assert token_call.kwargs["token_total"] == 425
        assert token_call.kwargs["agent"] == {"model": "sum-model"}

    async def test_usage_tokens_ignore_non_dict_entries(self):
        callback = MagicMock()
        callback.usage_metadata = {
            "model_a": {"input_tokens": 10, "output_tokens": 5},
            "total": 15,  # not a dict — must be skipped, not summed
        }
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 10
        assert token_call.kwargs["token_output"] == 5
        assert token_call.kwargs["token_total"] == 15

    async def test_usage_none_metadata_logs_zeroes(self):
        callback = MagicMock()
        callback.usage_metadata = None
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 0
        assert token_call.kwargs["token_output"] == 0
        assert token_call.kwargs["token_total"] == 0

    async def test_no_callback_means_no_token_logging(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("response", {}),
            ),
        ):
            await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert not any("token_input" in c.kwargs for c in mock_log.set.call_args_list)

    async def test_setup_error_returns_error_tuple(self):
        p = _common_patches()
        with (
            patch.object(
                agent_module,
                "construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("silent boom"),
            ),
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert msg == "Error when calling silent agent: silent boom"
        assert data == {}

    async def test_execute_error_returns_error_tuple(self):
        p = _common_patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
            patch.object(
                agent_module,
                "execute_graph_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("execute failed"),
            ),
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert msg == "Error when calling silent agent: execute failed"
        assert data == {}
        mock_log.error.assert_called_once()
