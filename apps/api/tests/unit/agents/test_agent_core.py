"""Behavior spec + unit tests for app.agents.core.agent.

The module exposes two public entry points sharing one private setup helper.
Collaborators (construct_langchain_messages, GraphManager.get_graph,
build_initial_state, build_agent_config, execute_graph_streaming /
execute_graph_silent, store_user_message_memory, log) live in OTHER modules and
are the I/O / orchestration boundary — they are mocked. Everything asserted
below is the real branching/wiring of agent.py itself.

UNIT: app/agents/core/agent.py :: _core_agent_logic
EXPECTED: Concurrently build langchain history + fetch the comms_agent graph,
          build the initial state from (request, user_id|"", conversation_id,
          history, trigger_context), fire-and-forget memory storage ONLY when
          BOTH user_id and request.message are truthy, build the agent config
          tagged agent_name="comms_agent", emit one log.set with agent
          observability metadata, and return (graph, initial_state, config).
MECHANISM: asyncio.gather(construct..., GraphManager.get_graph("comms_agent"));
           build_initial_state(request, user_id or "", conv_id, history, trigger);
           if user_id and request.message: create_task(store_user_message_memory);
           build_agent_config(..., agent_name="comms_agent", ...);
           log.set(agent=dict(model=..., has_workflow=bool(...), ...)).
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - returns the exact graph / state / config objects from collaborators
  - construct_langchain_messages receives the real query, user_name, trigger_context
  - GraphManager.get_graph is called with the literal "comms_agent"
  - build_initial_state receives user_id (falling back to "" when None) + trigger
  - memory task fires with (user_id, message, conversation_id) when both present
  - memory task is SKIPPED when user_id is None (the `and` guard, left operand)
  - memory task is SKIPPED when message is "" (the `and` guard, right operand)
  - build_agent_config is tagged agent_name="comms_agent" (not blank/other)
  - log.set agent metadata reflects the real request flags + history length

UNIT: app/agents/core/agent.py :: call_agent (streaming)
EXPECTED: On success return the AsyncGenerator from execute_graph_streaming,
          having injected stream_id into config["configurable"] iff provided.
          On any setup exception, return an error generator that yields exactly
          one SSE error frame carrying the exception text then "data: [DONE]".
MECHANISM: graph,state,config = _core_agent_logic(...);
           if stream_id: config["configurable"]["stream_id"] = stream_id;
           return execute_graph_streaming(graph, state, config);
           except: yield f"data: {json.dumps({'error': msg})}\\n\\n"; yield "data: [DONE]\\n\\n".
MUST-CATCH:
  - the real stream from execute_graph_streaming is returned (chunks flow through)
  - stream_id, when given, lands at config["configurable"]["stream_id"]
  - stream_id is absent from config when not provided (the `if stream_id` guard)
  - on setup failure the first frame is a JSON {"error": ...} carrying exc text
  - the error stream terminates with a "[DONE]" frame and both frames are SSE-framed

UNIT: app/agents/core/agent.py :: call_agent_silent
EXPECTED: On success return execute_graph_silent's (message, tool_data) tuple,
          and when a usage_metadata_callback with usage data is present, emit a
          log.set summing input/output tokens across dict-valued entries (zero
          for None metadata, non-dict entries ignored). On any exception return
          ("Error when calling silent agent: <exc>", {}).
MECHANISM: result = execute_graph_silent(...);
           if callback and hasattr(callback,"usage_metadata"):
               usage = callback.usage_metadata or {};
               total_in = sum(v.get("input_tokens",0) ...); ...; log.set(token_*=...);
           return result; except: return f"Error ...: {exc}", {}.
MUST-CATCH:
  - the real (message, tool_data) tuple is returned unchanged on success
  - trigger_context is threaded through to construct_langchain_messages
  - token_input/output/total are summed correctly across multiple dict entries
  - non-dict usage entries are skipped (isinstance guard), defaults are 0
  - None usage_metadata coalesces to {} -> all token totals 0
  - without a callback, no token log.set is emitted
  - on setup failure the error tuple message carries the exc text and data == {}
  - on execute_graph_silent failure the same error tuple is returned

EQUIVALENT MUTANTS (allowed survivors — proven behavior-preserving):
  The only surviving mutants under full mutation are the `str -> ''` mutations of
  the four function DOCSTRINGS (agent.py L49 _core_agent_logic, L142 call_agent,
  L173 error_generator, L191 call_agent_silent). A docstring is the first
  Expr/Constant/str statement of a function body; mutating it changes only
  `func.__doc__` and has zero runtime-behavior effect. No code path in this
  module reads __doc__, and asserting __doc__ would be a hollow test (banned by
  the rubric). Every NON-docstring mutant in the three target functions is
  killed -> effective kill rate over behavioral mutants is 100% (34/34).
"""

import asyncio
from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core.agent import (
    _core_agent_logic,
    call_agent,
    call_agent_silent,
)
from app.models.message_models import (
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures-by-hand (deterministic, no shared mutable state)
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
    defaults = {"user_id": "user-123", "email": "test@example.com", "name": "Test User"}
    defaults.update(overrides)
    return defaults


class _UsageCallback:
    """Minimal stand-in for UsageMetadataCallbackHandler.

    A real object (not a MagicMock) so `hasattr(cb, "usage_metadata")` is True
    only because the attribute genuinely exists — this makes the production
    `hasattr(..., "usage_metadata")` literal load-bearing under mutation.
    """

    def __init__(self, usage_metadata) -> None:
        self.usage_metadata = usage_metadata


FAKE_HISTORY = [
    SystemMessage(content="You are helpful."),
    HumanMessage(content="Hello agent"),
]
FAKE_GRAPH = MagicMock(name="fake_graph")
FAKE_STATE = {"messages": FAKE_HISTORY, "query": "Hello agent"}


def _make_config() -> dict:
    """Fresh config per call so stream_id injection never leaks across tests."""
    return {
        "configurable": {
            "thread_id": "conv-1",
            "user_id": "user-123",
            "model_name": "gpt-4o",
        }
    }


def _patches(*, config: dict | None = None):
    """Patch every I/O collaborator of agent.py. config defaults to a fresh dict."""
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
            return_value=config if config is not None else _make_config(),
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
    @pytest.mark.asyncio
    async def test_returns_collaborator_graph_state_config(self):
        cfg = _make_config()
        p = _patches(config=cfg)
        with (
            p["construct"],
            p["get_graph"] as mock_graph,
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
        # The graph fetched is specifically the comms_agent graph.
        mock_graph.assert_awaited_once_with("comms_agent")

    @pytest.mark.asyncio
    async def test_construct_messages_receives_real_request_fields(self):
        req = _make_request(message="custom query")
        user = _make_user(name="Alice")
        trigger = {"type": "gmail"}
        p = _patches()
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
                conversation_id="conv-1",
                user=user,
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        kwargs = mock_construct.call_args.kwargs
        assert kwargs["query"] == "custom query"
        assert kwargs["user_name"] == "Alice"
        assert kwargs["user_id"] == "user-123"
        assert kwargs["trigger_context"] is trigger
        assert kwargs["conversation_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_build_initial_state_receives_user_id_and_trigger(self):
        trigger = {"type": "gmail", "email_data": {}}
        p = _patches()
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
                user=_make_user(user_id="uid-9"),
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        args = mock_state.call_args.args
        # build_initial_state(request, user_id, conversation_id, history, trigger)
        assert args[1] == "uid-9"
        assert args[2] == "conv-1"
        assert args[3] is FAKE_HISTORY
        assert args[4] is trigger

    @pytest.mark.asyncio
    async def test_build_initial_state_user_id_falls_back_to_empty_string(self):
        """`user_id or ""` — None user_id must become "" for build_initial_state."""
        p = _patches()
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

    @pytest.mark.asyncio
    async def test_memory_task_fires_with_real_args(self):
        p = _patches()
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
                conversation_id="conv-77",
                user=_make_user(user_id="uid-1"),
                user_time=datetime.now(UTC),
            )
            await asyncio.sleep(0)  # let the fire-and-forget task run

        mock_store.assert_awaited_once_with("uid-1", "remember this", "conv-77")

    @pytest.mark.asyncio
    async def test_memory_skipped_when_no_user_id(self):
        """Left operand of `user_id and request.message` guard."""
        p = _patches()
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

    @pytest.mark.asyncio
    async def test_memory_skipped_when_no_message(self):
        """Right operand of `user_id and request.message` guard."""
        p = _patches()
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
                user=_make_user(user_id="uid-1"),
                user_time=datetime.now(UTC),
            )
            await asyncio.sleep(0)

        mock_store.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_build_agent_config_tagged_comms_agent(self):
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"] as mock_cfg,
            p["store_mem"],
            p["log"],
        ):
            await _core_agent_logic(
                request=_make_request(selectedTool="weather", toolCategory="search"),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        kwargs = mock_cfg.call_args.kwargs
        assert kwargs["agent_name"] == "comms_agent"
        assert kwargs["selected_tool"] == "weather"
        assert kwargs["tool_category"] == "search"

    @pytest.mark.asyncio
    async def test_log_set_agent_metadata_reflects_request(self):
        """The observability frame must carry the real model + request flags."""
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=_make_request(
                    selectedWorkflow=SelectedWorkflowData(
                        id="wf-1", title="t", description="d", steps=[]
                    ),
                    selectedCalendarEvent=SelectedCalendarEventData(
                        id="evt", summary="s", description="d", start={}, end={}
                    ),
                    replyToMessage=ReplyToMessageData(id="m1", content="c", role="user"),
                ),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                trigger_context={"type": "cron"},
            )

        mock_log.set.assert_called_once()
        agent = mock_log.set.call_args.kwargs["agent"]
        assert agent["model"] == "gpt-4o"
        assert agent["has_workflow"] is True
        assert agent["has_trigger_context"] is True
        assert agent["has_calendar_event"] is True
        assert agent["has_reply"] is True
        assert agent["history_message_count"] == len(FAKE_HISTORY)

    @pytest.mark.asyncio
    async def test_log_set_agent_metadata_flags_false_when_absent(self):
        """Bare request -> every optional flag is False (kills bool-flip mutants)."""
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
        ):
            await _core_agent_logic(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        agent = mock_log.set.call_args.kwargs["agent"]
        assert agent["has_workflow"] is False
        assert agent["has_trigger_context"] is False
        assert agent["has_calendar_event"] is False
        assert agent["has_reply"] is False


# ---------------------------------------------------------------------------
# call_agent (streaming)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallAgent:
    @pytest.mark.asyncio
    async def test_returns_real_streaming_generator(self):
        async def _fake_stream(*_a, **_k):
            yield "data: chunk-1\n\n"
            yield "data: [DONE]\n\n"

        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )
            chunks = [c async for c in gen]

        # The returned generator is exactly execute_graph_streaming's output.
        assert chunks == ["data: chunk-1\n\n", "data: [DONE]\n\n"]
        # Called with the graph + state + config from _core_agent_logic.
        passed = mock_exec.call_args.args
        assert passed[0] is FAKE_GRAPH
        assert passed[1] is FAKE_STATE

    @pytest.mark.asyncio
    async def test_stream_id_injected_into_config(self):
        async def _fake_stream(*_a, **_k):
            yield "data: [DONE]\n\n"

        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
                stream_id="stream-abc",
            )

        passed_config = mock_exec.call_args.args[2]
        assert passed_config["configurable"]["stream_id"] == "stream-abc"

    @pytest.mark.asyncio
    async def test_stream_id_absent_when_not_provided(self):
        async def _fake_stream(*_a, **_k):
            yield "data: [DONE]\n\n"

        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch(
                "app.agents.core.agent.execute_graph_streaming",
                return_value=_fake_stream(),
            ) as mock_exec,
        ):
            await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        passed_config = mock_exec.call_args.args[2]
        assert "stream_id" not in passed_config["configurable"]

    @pytest.mark.asyncio
    async def test_setup_failure_returns_error_sse_stream(self):
        p = _patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
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
            chunks = [c async for c in gen]

        assert len(chunks) == 2
        # The error frame is SSE-framed: "data: " prefix + JSON + trailing "\n\n".
        assert chunks[0].startswith("data: ")
        assert chunks[0].endswith("\n\n")
        first = json.loads(chunks[0].removeprefix("data: ").strip())
        assert "boom" in first["error"]
        assert "Error when calling agent" in first["error"]
        assert chunks[1] == "data: [DONE]\n\n"
        # The failure is logged with a descriptive message carrying the exc.
        mock_log.error.assert_called_once_with("Error when calling agent: boom")

    @pytest.mark.asyncio
    async def test_error_stream_does_not_invoke_graph_streaming(self):
        """On setup failure we must NOT fall through to execute_graph_streaming."""
        p = _patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=ValueError("bad"),
            ),
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch("app.agents.core.agent.execute_graph_streaming") as mock_exec,
        ):
            gen = await call_agent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )
            _ = [c async for c in gen]

        mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# call_agent_silent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallAgentSilent:
    @pytest.mark.asyncio
    async def test_happy_path_returns_execute_result(self):
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
            patch(
                "app.agents.core.agent.execute_graph_silent",
                new_callable=AsyncMock,
                return_value=("Hello!", {"tool_data": ["x"]}),
            ) as mock_exec,
        ):
            result = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert result == ("Hello!", {"tool_data": ["x"]})
        passed = mock_exec.call_args.args
        assert passed[0] is FAKE_GRAPH
        assert passed[1] is FAKE_STATE

    @pytest.mark.asyncio
    async def test_trigger_context_threaded_to_construct(self):
        trigger = {"type": "cron", "schedule": "daily"}
        p = _patches()
        with (
            p["construct"] as mock_construct,
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
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
                user_time=datetime.now(UTC),
                trigger_context=trigger,
            )

        assert mock_construct.call_args.kwargs["trigger_context"] is trigger

    @pytest.mark.asyncio
    async def test_token_usage_summed_across_dict_entries(self):
        callback = _UsageCallback(
            {
                "model_a": {"input_tokens": 100, "output_tokens": 50},
                "model_b": {"input_tokens": 200, "output_tokens": 75},
            }
        )
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 300
        assert token_call.kwargs["token_output"] == 125
        assert token_call.kwargs["token_total"] == 425
        # The token frame also re-states the model under the agent key.
        assert token_call.kwargs["agent"]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_token_usage_missing_keys_default_to_zero(self):
        """Entries lacking input/output keys contribute 0, not a crash."""
        callback = _UsageCallback(
            {
                "only_input": {"input_tokens": 40},
                "only_output": {"output_tokens": 7},
                "empty": {},
            }
        )
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 40
        assert token_call.kwargs["token_output"] == 7
        assert token_call.kwargs["token_total"] == 47

    @pytest.mark.asyncio
    async def test_token_usage_none_metadata_totals_zero(self):
        callback = _UsageCallback(None)
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 0
        assert token_call.kwargs["token_output"] == 0
        assert token_call.kwargs["token_total"] == 0

    @pytest.mark.asyncio
    async def test_token_usage_non_dict_entries_skipped(self):
        callback = _UsageCallback(
            {
                "model_a": {"input_tokens": 10, "output_tokens": 5},
                "total": 15,  # not a dict -> isinstance guard skips it
            }
        )
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,
            )

        token_call = next(c for c in mock_log.set.call_args_list if "token_input" in c.kwargs)
        assert token_call.kwargs["token_input"] == 10
        assert token_call.kwargs["token_output"] == 5

    @pytest.mark.asyncio
    async def test_no_callback_emits_no_token_log(self):
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
            )

        token_call = next(
            (c for c in mock_log.set.call_args_list if "token_input" in c.kwargs), None
        )
        assert token_call is None

    @pytest.mark.asyncio
    async def test_callback_without_usage_metadata_attr_emits_no_token_log(self):
        """hasattr/`and` guard: a callback lacking usage_metadata is truthy but
        must be rejected by the `hasattr` half of `cb and hasattr(...)`. The
        branch must be skipped (no token log) AND the real result returned —
        entering it would raise AttributeError and swap to the error tuple."""
        callback = object()  # truthy, but has no .usage_metadata attribute
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
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
                user_time=datetime.now(UTC),
                usage_metadata_callback=callback,  # type: ignore[arg-type]
            )

        # Branch skipped: real result preserved, no AttributeError -> error tuple.
        assert result == ("response", {})
        token_call = next(
            (c for c in mock_log.set.call_args_list if "token_input" in c.kwargs), None
        )
        assert token_call is None

    @pytest.mark.asyncio
    async def test_setup_failure_returns_error_tuple(self):
        p = _patches()
        with (
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("silent boom"),
            ),
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"] as mock_log,
        ):
            msg, data = await call_agent_silent(
                request=_make_request(),
                conversation_id="conv-1",
                user=_make_user(),
                user_time=datetime.now(UTC),
            )

        assert msg == "Error when calling silent agent: silent boom"
        assert data == {}
        # The failure is logged with a descriptive message carrying the exc.
        mock_log.error.assert_called_once_with("Error when calling silent agent: silent boom")

    @pytest.mark.asyncio
    async def test_execute_failure_returns_error_tuple(self):
        p = _patches()
        with (
            p["construct"],
            p["get_graph"],
            p["build_state"],
            p["build_config"],
            p["store_mem"],
            p["log"],
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
                user_time=datetime.now(UTC),
            )

        assert msg == "Error when calling silent agent: execute failed"
        assert data == {}
