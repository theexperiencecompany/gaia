"""Behaviour-spec mutation-verified tests for the chat-service streaming pipeline.

UNIT: app/services/chat_service.py
SCOPE: run_chat_stream_background, _run_chat_stream, _start_description_task,
       _wait_for_http_subscriber, _initialize_new_conversation,
       _save_conversation_async, _accumulate_executor_tool_data,
       _process_token_usage_and_cost.
TIER: unit — Redis/stream_manager, MongoDB, the agent (call_agent), the LLM
      usage callback, payment_service and the rate limiter are mocked at the
      I/O boundary; all service control-flow runs for real.

This is a P0 critical-path module (chat orchestration, message ordering, billing,
persistence). Kill-gate = 1.0.

================================ BEHAVIOUR SPEC ================================

UNIT: run_chat_stream_background
EXPECTED: thin wrapper that opens a `wide_task("chat_stream", ...)` logging
          context and delegates to _run_chat_stream with the SAME arguments.
MECHANISM: async with wide_task(...): await _run_chat_stream(stream_id=..., body=...,
           user=..., user_time=..., conversation_id=..., source=..., start_event=...).
MUST-CATCH:
  - every argument it receives is forwarded unchanged to _run_chat_stream
    (a mutated forwarding would persist the wrong conversation / lose data).

UNIT: _run_chat_stream  (the orchestrator)
EXPECTED: drives the agent stream, publishes an init chunk + SSE chunks to Redis,
          saves the conversation exactly once on the happy path (early save), waits
          for a spawned executor, then publishes [DONE] and completes the stream.
          On agent failure it publishes an error chunk BEFORE set_error and still
          saves via the finally fallback. Always cleans up Redis + deregisters
          in-process orchestration state.
MECHANISM / MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - is_new_conversation := body.conversation_id is None OR
      (body.is_onboarding_demo AND not <conversation found in Mongo>).
      * conversation_id None  -> new path (create_conversation + description task).
      * conversation_id set, not onboarding -> existing path, NO Mongo lookup, NO
        description task.
      * conversation_id set, onboarding demo, Mongo MISS -> treated as new.
      * conversation_id set, onboarding demo, Mongo HIT  -> treated as existing.
  - new path: first published chunk carries "conversation_id" (init frame from
    _initialize_new_conversation); existing path: first published chunk carries
    "user_message_id"+"bot_message_id"+"stream_id" but NOT "conversation_id".
  - the agent's "data: [DONE]" sentinel inside the loop is skipped (not published
    mid-loop); the terminal [DONE] is published exactly once at the end.
  - a "nostream: " chunk with a dict containing "complete_message" sets
    complete_message (later saved) and is NEVER published to the client; a
    "nostream:" chunk WITHOUT "complete_message" resets complete_message to "".
  - a "data: " chunk is routed through process_data_chunk; tool_data / tool_output /
    follow_up_actions are accumulated and the merged tool_data is what gets saved.
  - when stream_manager.is_cancelled() is True the loop breaks (remaining agent
    chunks are NOT processed) yet the conversation is still saved.
  - the conversation is saved exactly once on success (early save sets _saved=True so
    the finally fallback does NOT save again).
  - on agent exception: an error chunk {"error": <msg>} is published BEFORE set_error
    is called, set_error is called, and the finally fallback save still runs once.
  - executor wait: only when `not is_cancelled AND was_executor_spawned(stream_id)`
    do we await executor_done and push accumulated executor tool_data to Mongo with
    the correct {user_id, conversation_id, messages.message_id} filter and a
    $push/$each on messages.$.tool_data.
  - finally ALWAYS runs stream_manager.cleanup(stream_id) and deregisters state.

UNIT: _start_description_task
EXPECTED: returns None for an existing conversation; for a new conversation returns
          an asyncio.Task that calls generate_and_update_description with the LAST
          message and the body's selected tool/workflow (or None when falsy).
MUST-CATCH:
  - is_new_conversation False -> None (no description generated).
  - is_new_conversation True  -> generate_and_update_description called once with the
    last message of body.messages.

UNIT: _wait_for_http_subscriber
EXPECTED: returns immediately when start_event is None or already set; otherwise
          waits up to 5s for the event; on TimeoutError it swallows and proceeds.
MUST-CATCH:
  - start_event None -> returns without waiting.
  - start_event already set -> returns without waiting.
  - start_event never set -> waits then proceeds without raising (timeout swallowed).

UNIT: _initialize_new_conversation
EXPECTED: creates the conversation via create_conversation and returns the SSE init
          frame carrying conversation_id + description + both message ids + stream_id.
MUST-CATCH:
  - create_conversation called with the LAST message + selectedTool/selectedWorkflow.
  - returned frame contains conversation_id, conversation_description, the exact
    user_message_id / bot_message_id passed in, and the stream_id.

UNIT: _save_conversation_async
EXPECTED: persists a [user_message, bot_message] pair via update_messages with the
          correct conversation_id; user content comes from the last message (else
          falls back to body.message); bot carries complete_message + tool_data +
          metadata; token usage is processed only when metadata AND user_id exist,
          and a token-processing failure never blocks the save.
MUST-CATCH:
  - exactly two messages saved, ordered [user, bot]; user.response from last message,
    falling back to body.message when messages is empty.
  - bot.response == complete_message; tool_data keys are applied onto the bot message.
  - message ids set on both models; conversation_id propagated to UpdateMessagesRequest.
  - _process_token_usage_and_cost called once with (user_id, metadata) when metadata is
    truthy; NOT called when metadata is empty; its failure is swallowed (save proceeds).

UNIT: _accumulate_executor_tool_data
EXPECTED: drains the per-stream tool-event collector into a flat tool_data list,
          backfilling ONLY tool_calls_data outputs and grouping subagents; returns
          [] when there is no collector.
MUST-CATCH:
  - no collector registered -> returns [].
  - tool_calls_data entry gets its data.output backfilled from a matching tool_output
    event; the returned list contains the accumulated entry.

UNIT: _process_token_usage_and_cost
EXPECTED: prices each model's usage, sums credits, and increments the tiered limiter
          ONLY when total credits > 0; cache_read is read from input_token_details
          first; all exceptions are swallowed (debug-logged, never raised).
MUST-CATCH:
  - per-model cost summed via calculate_token_cost with the right tokens, including
    cached_tokens taken from input_token_details.cache_read.
  - tiered_limiter.check_and_increment called once with the summed credits when > 0.
  - check_and_increment NOT called when total credits == 0.
  - an entry with input_tokens==0 and output_tokens==0 is skipped (no pricing call).

EQUIVALENT MUTANTS (allowed survivors — behaviour-preserving, proven by line mapping
against the mutation harness; none alters a return value, persisted record, raised
exception, or client-streamed payload):
  - DOCSTRINGS: every function's `\"\"\"...\"\"\"` (str -> '') — no runtime effect.
  - LOG MESSAGE STRINGS / EVENT NAMES: log.info/log.warning/log.error/log.debug message
    text and structured-event names ("background_stream_error",
    "token_usage_processing_failed", "chat_stream" wide-task label, the cancelled/
    timeout/fallback log lines) — observability only, never asserted as behaviour.
  - LOG KWARG VALUES: `exc_info=True` (-> False) on error logs; the `"model"` key read
    in `log.get().get("model", ...)`; `round(total_credits, 6)` (-> 7) precision of the
    logged cost_usd; the `user_id = user.get("user_id")` key feeding only log context.
  - DEAD / UNREACHABLE CONSTANT: `max(total_input, 1)` const 1 (-> 2) — the `1` is only
    reached when total_input is 0, but the surrounding `... if total_input else 0.0`
    short-circuits to 0.0 in that case, so the denominator literal is never used.
  - LOG-ONLY ARITHMETIC PRECISION: cache_hit_rate `round(..., 4)` (-> 5) — the asserted
    value 0.25 is exact at both precisions; the field is log-only.
  - MONGO PROJECTION FLAG: `{"_id": 1}` const 1 (-> 2) and key (-> "") in the onboarding
    existence probe — find_one's result is consumed only for truthiness, so the
    projection content cannot change behaviour (MongoDB treats any non-zero include
    flag identically).
  - SSE ROUTING `startswith("data: ")` (-> startswith("")): a "" prefix routes every
    chunk through process_data_chunk, which re-publishes any chunk it cannot parse —
    so the client-observable output is identical for all realistic chunk shapes.
  - EXECUTOR-WAIT TIMEOUT `timeout=1800` (-> 1801): the executor-done event is pre-set
    in tests, so the wait returns before any timeout value is reached.
"""

import asyncio
from collections.abc import AsyncGenerator, Iterator
import contextlib
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import inbox
from app.models.message_models import MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.chat_service import (
    _accumulate_executor_tool_data,
    _initialize_new_conversation,
    _process_token_usage_and_cost,
    _save_conversation_async,
    _start_description_task,
    _wait_for_http_subscriber,
    run_chat_stream_background,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user() -> dict:
    return {"user_id": "user_abc", "email": "tester@example.com"}


@pytest.fixture
def new_conv_body() -> MessageRequestWithHistory:
    """Request with no conversation_id -> a NEW conversation."""
    return MessageRequestWithHistory(
        message="Hello GAIA",
        messages=[{"role": "user", "content": "Hello GAIA"}],
        conversation_id=None,
    )


@pytest.fixture
def existing_conv_body() -> MessageRequestWithHistory:
    """Request referencing an already-existing conversation."""
    return MessageRequestWithHistory(
        message="Follow-up",
        messages=[{"role": "user", "content": "Follow-up"}],
        conversation_id="conv_existing_123",
    )


@pytest.fixture(autouse=True)
def _isolate_inbox_state():
    """The inbox module keeps per-stream orchestration state in module-level dicts
    that survive across tests. Snapshot and restore them so no test leaks a spawned
    flag / collector into a sibling (the source of the original suite's order-dependent
    failure under serial execution)."""
    spawned = set(inbox._executor_spawned_streams)
    done = dict(inbox._executor_done_events)
    collectors = dict(inbox._executor_tool_event_collectors)
    pending = dict(inbox._pending_bg_subagents)
    results = dict(inbox._bg_subagent_results)
    yield
    inbox._executor_spawned_streams.clear()
    inbox._executor_spawned_streams.update(spawned)
    inbox._executor_done_events.clear()
    inbox._executor_done_events.update(done)
    inbox._executor_tool_event_collectors.clear()
    inbox._executor_tool_event_collectors.update(collectors)
    inbox._pending_bg_subagents.clear()
    inbox._pending_bg_subagents.update(pending)
    inbox._bg_subagent_results.clear()
    inbox._bg_subagent_results.update(results)


# ---------------------------------------------------------------------------
# Agent-stream builders + stream_manager mock
# ---------------------------------------------------------------------------


async def _done_only_stream() -> AsyncGenerator[str, None]:
    yield "data: [DONE]\n\n"


def _make_stream_manager_mock(is_cancelled: bool = False) -> MagicMock:
    m = MagicMock()
    m.publish_chunk = AsyncMock()
    m.is_cancelled = AsyncMock(return_value=is_cancelled)
    m.update_progress = AsyncMock()
    m.complete_stream = AsyncMock()
    m.set_error = AsyncMock()
    m.cleanup = AsyncMock()
    m.get_progress = AsyncMock(return_value=None)
    return m


@contextlib.contextmanager
def _run_stream_patches(
    sm: MagicMock,
    *extra_patches,
    agent_stream: AsyncGenerator[str, None] | None = None,
    agent_side_effect: Exception | None = None,
    save_mock: AsyncMock | None = None,
) -> Iterator[None]:
    """Patch every I/O boundary _run_chat_stream touches and enter all of them via a
    single ExitStack. The agent is configured via the ``call_agent`` mock (it is
    awaited and returns an async generator). Pass test-specific patches positionally
    in ``extra_patches`` to layer them on top within the same ``with`` block."""
    call_agent_mock = AsyncMock()
    if agent_side_effect is not None:
        call_agent_mock.side_effect = agent_side_effect
    else:
        call_agent_mock.return_value = agent_stream

    base = (
        patch("app.services.chat_service.stream_manager", sm),
        patch("app.utils.stream_utils.stream_manager", sm),
        patch("app.services.chat_service.call_agent", new=call_agent_mock),
        patch(
            "app.services.chat_service._save_conversation_async",
            new=(save_mock or AsyncMock()),
        ),
        patch("app.services.chat_service.UsageMetadataCallbackHandler", MagicMock()),
    )
    with contextlib.ExitStack() as stack:
        for cm in (*base, *extra_patches):
            stack.enter_context(cm)
        yield


# ===========================================================================
# run_chat_stream_background — argument-forwarding wrapper
# ===========================================================================


@pytest.mark.unit
class TestRunChatStreamBackgroundWrapper:
    async def test_forwards_all_arguments_to_run_chat_stream(self, test_user, existing_conv_body):
        """Every arg the wrapper receives must reach _run_chat_stream unchanged."""
        inner = AsyncMock()
        user_time = datetime(2025, 1, 1, tzinfo=UTC)
        start_event = MagicMock()
        with patch("app.services.chat_service._run_chat_stream", new=inner):
            await run_chat_stream_background(
                stream_id="sid_fwd",
                body=existing_conv_body,
                user=test_user,
                user_time=user_time,
                conversation_id="conv_fwd",
                source="telegram",
                start_event=start_event,
            )

        inner.assert_awaited_once()
        kw = inner.call_args.kwargs
        assert kw["stream_id"] == "sid_fwd"
        assert kw["body"] is existing_conv_body
        assert kw["user"] is test_user
        assert kw["user_time"] is user_time
        assert kw["conversation_id"] == "conv_fwd"
        assert kw["source"] == "telegram"
        assert kw["start_event"] is start_event


# ===========================================================================
# _run_chat_stream — new vs existing conversation routing
# ===========================================================================


@pytest.mark.unit
class TestRunChatStreamNewVsExisting:
    async def test_new_conversation_publishes_init_chunk_with_conversation_id(
        self, test_user, new_conv_body
    ):
        sm = _make_stream_manager_mock()
        with _run_stream_patches(
            sm,
            patch(
                "app.services.chat_service.create_conversation",
                new=AsyncMock(return_value={"conversation_description": "Test conv"}),
            ),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="Test conv"),
            ),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_new",
                body=new_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="new_conv_id",
            )

        first_chunk = sm.publish_chunk.call_args_list[0].args[1]
        payload = json.loads(first_chunk[6:])
        assert payload["conversation_id"] == "new_conv_id"
        assert payload["conversation_description"] == "Test conv"

    async def test_existing_conversation_init_chunk_omits_conversation_id(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        with _run_stream_patches(sm, agent_stream=_done_only_stream()):
            await run_chat_stream_background(
                stream_id="stream_exist",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        first_chunk = sm.publish_chunk.call_args_list[0].args[1]
        assert first_chunk.startswith("data: ")
        assert first_chunk.endswith("\n\n")  # SSE frame terminator
        payload = json.loads(first_chunk[6:])
        assert payload["user_message_id"]
        assert payload["bot_message_id"]
        assert payload["stream_id"] == "stream_exist"
        assert "conversation_id" not in payload

    async def test_onboarding_demo_with_mongo_miss_is_treated_as_new(self, test_user):
        """is_onboarding_demo + no existing Mongo doc => NEW conversation path."""
        body = MessageRequestWithHistory(
            message="demo",
            messages=[{"role": "user", "content": "demo"}],
            conversation_id="demo_conv",
            is_onboarding_demo=True,
        )
        sm = _make_stream_manager_mock()
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)  # Mongo MISS
        create_mock = AsyncMock(return_value={"conversation_description": "Demo"})
        with _run_stream_patches(
            sm,
            patch("app.services.chat_service.conversations_collection", coll),
            patch("app.services.chat_service.create_conversation", new=create_mock),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="Demo"),
            ),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_demo_miss",
                body=body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="demo_conv",
            )

        create_mock.assert_awaited_once()
        first_chunk = sm.publish_chunk.call_args_list[0].args[1]
        assert "conversation_id" in json.loads(first_chunk[6:])
        # The existence probe must scope to THIS user + conversation (cross-user isolation).
        probe_filter = coll.find_one.call_args.args[0]
        assert probe_filter == {"user_id": "user_abc", "conversation_id": "demo_conv"}

    async def test_onboarding_demo_with_mongo_hit_is_treated_as_existing(self, test_user):
        """is_onboarding_demo but the conversation already exists => EXISTING path."""
        body = MessageRequestWithHistory(
            message="demo",
            messages=[{"role": "user", "content": "demo"}],
            conversation_id="demo_conv",
            is_onboarding_demo=True,
        )
        sm = _make_stream_manager_mock()
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value={"_id": "x"})  # Mongo HIT
        create_mock = AsyncMock(return_value={"conversation_description": "Demo"})
        with _run_stream_patches(
            sm,
            patch("app.services.chat_service.conversations_collection", coll),
            patch("app.services.chat_service.create_conversation", new=create_mock),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="Demo"),
            ),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_demo_hit",
                body=body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="demo_conv",
            )

        create_mock.assert_not_called()
        coll.find_one.assert_awaited_once()
        first_chunk = sm.publish_chunk.call_args_list[0].args[1]
        assert "conversation_id" not in json.loads(first_chunk[6:])


# ===========================================================================
# _run_chat_stream — streaming-loop behaviour
# ===========================================================================


@pytest.mark.unit
class TestRunChatStreamLoopBehaviour:
    async def test_terminal_done_published_exactly_once(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with _run_stream_patches(sm, agent_stream=_done_only_stream()):
            await run_chat_stream_background(
                stream_id="stream_done",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        published = [c.args[1] for c in sm.publish_chunk.call_args_list]
        # The agent emitted [DONE] inside the loop (must be skipped); the service
        # publishes exactly one terminal [DONE] at the end.
        assert published.count("data: [DONE]\n\n") == 1
        sm.complete_stream.assert_awaited_once_with("stream_done")

    async def test_nostream_marker_sets_saved_complete_message_and_is_not_published(
        self, test_user, existing_conv_body
    ):
        complete_text = "The final answer is here."

        async def agent():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            yield f"nostream: {json.dumps({'complete_message': complete_text})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_ns_marker",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        assert save_mock.call_args.kwargs["complete_message"] == complete_text
        published = [c.args[1] for c in sm.publish_chunk.call_args_list]
        # The internal "nostream: " marker must never be forwarded to the client.
        assert not any(chunk.startswith("nostream: ") for chunk in published)

    async def test_nostream_without_complete_message_resets_to_empty(
        self, test_user, existing_conv_body
    ):
        """A nostream dict lacking 'complete_message' resets complete_message to '' via the
        else branch — it must NOT crash by indexing a missing key. Kills both the
        `else: complete_message = ''` branch and the `isinstance(...) and "complete_message"
        in ...` boolop (an `and`->`or` mutant would KeyError into the error path)."""

        async def agent():
            yield f"nostream: {json.dumps({'something_else': 'x'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_nostream_empty",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        assert save_mock.call_args.kwargs["complete_message"] == ""
        # The happy path completes cleanly: no error was raised/published.
        sm.set_error.assert_not_called()
        sm.complete_stream.assert_awaited_once()

    async def test_tool_data_chunks_accumulated_into_saved_message(
        self, test_user, existing_conv_body
    ):
        async def agent():
            payload = {
                "tool_data": {
                    "tool_name": "search_results",
                    "data": {"items": ["r1"]},
                    "timestamp": "2025-01-01T00:00:00+00:00",
                }
            }
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_tools",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        saved = save_mock.call_args.kwargs["tool_data"]
        assert saved["tool_data"][0]["tool_name"] == "search_results"

    async def test_tool_output_merged_into_tool_calls_data_before_save(
        self, test_user, existing_conv_body
    ):
        async def agent():
            yield (
                "data: "
                + json.dumps(
                    {
                        "tool_data": {
                            "tool_name": "tool_calls_data",
                            "data": {"tool_call_id": "call_abc", "name": "search"},
                            "timestamp": "t",
                        }
                    }
                )
                + "\n\n"
            )
            yield (
                "data: "
                + json.dumps(
                    {"tool_output": {"tool_call_id": "call_abc", "output": "search results"}}
                )
                + "\n\n"
            )
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_merge",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        entries = save_mock.call_args.kwargs["tool_data"]["tool_data"]
        calls = next(e for e in entries if e.get("tool_name") == "tool_calls_data")
        assert calls["data"]["output"] == "search results"

    async def test_follow_up_actions_published_as_separate_event(
        self, test_user, existing_conv_body
    ):
        async def agent():
            yield f"data: {json.dumps({'follow_up_actions': ['Action A', 'Action B']})}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        with _run_stream_patches(sm, agent_stream=agent()):
            await run_chat_stream_background(
                stream_id="stream_fu",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        published = [c.args[1] for c in sm.publish_chunk.call_args_list]
        fu = [c for c in published if c.startswith("data: ") and "follow_up_actions" in c]
        assert fu, "expected a follow_up_actions SSE event"
        assert json.loads(fu[0][6:])["follow_up_actions"] == ["Action A", "Action B"]

    async def test_non_data_non_nostream_chunk_published_verbatim(
        self, test_user, existing_conv_body
    ):
        """A chunk that is neither 'data: ' nor 'nostream: ' is forwarded as-is."""

        async def agent():
            yield "event: ping\n\n"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        with _run_stream_patches(sm, agent_stream=agent()):
            await run_chat_stream_background(
                stream_id="stream_verbatim",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        published = [c.args[1] for c in sm.publish_chunk.call_args_list]
        assert "event: ping\n\n" in published

    async def test_cancellation_breaks_loop_but_still_saves(self, test_user, existing_conv_body):
        pulled: list[str] = []

        async def agent():
            for i in range(5):
                pulled.append(f"yielded {i}")
                yield f"data: {json.dumps({'response': f'chunk {i}'})}\n\n"

        sm = _make_stream_manager_mock(is_cancelled=True)
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_cancel",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        # The loop breaks on the first cancelled check: only one agent chunk was pulled.
        assert len(pulled) == 1
        save_mock.assert_awaited_once()

    async def test_complete_message_recovered_from_redis_when_marker_missing(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(
            return_value={"complete_message": "recovered text", "tool_data": {}}
        )
        save_mock = AsyncMock()

        async def agent():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            yield "data: [DONE]\n\n"

        with _run_stream_patches(sm, agent_stream=agent(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_recover",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        assert save_mock.call_args.kwargs["complete_message"] == "recovered text"

    async def test_usage_metadata_saved_and_token_totals_logged(
        self, test_user, existing_conv_body
    ):
        """The LLM usage metadata is persisted with the bot message AND the aggregated
        token totals + cache-hit-rate are recorded on the wide-event model context.
        Kills the `usage_metadata or {}` boolop and the token-accounting log arithmetic."""
        usage = {
            "model-a": {
                "input_tokens": 100,
                "output_tokens": 40,
                "input_token_details": {"cache_read": 25},
            }
        }
        callback = MagicMock()
        callback.usage_metadata = usage
        callback_cls = MagicMock(return_value=callback)
        save_mock = AsyncMock()
        log_mock = MagicMock()
        log_mock.get.return_value = {}

        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch("app.utils.stream_utils.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch("app.services.chat_service._save_conversation_async", new=save_mock),
            patch("app.services.chat_service.UsageMetadataCallbackHandler", callback_cls),
            patch("app.services.chat_service.log", log_mock),
        ):
            await run_chat_stream_background(
                stream_id="stream_usage",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        # The real usage dict (not an empty {}) is persisted as the bot message metadata.
        assert save_mock.call_args.kwargs["metadata"] == usage
        # The aggregated token totals + cache-hit-rate are logged on the model context.
        model_logged = next(
            c.kwargs["model"] for c in log_mock.set.call_args_list if "model" in c.kwargs
        )
        assert model_logged["input_tokens"] == 100
        assert model_logged["output_tokens"] == 40
        assert model_logged["cached_tokens"] == 25
        assert model_logged["tokens_used"] == 140
        assert model_logged["cache_hit_rate"] == round(25 / 100, 4)

    async def test_conversation_description_published_for_new_conversation(
        self, test_user, new_conv_body
    ):
        """A new conversation's generated description is published as its own SSE frame
        (well-formed, terminated with \\n\\n) after the stream completes."""
        sm = _make_stream_manager_mock()
        with _run_stream_patches(
            sm,
            patch(
                "app.services.chat_service.create_conversation",
                new=AsyncMock(return_value={"conversation_description": "New Chat"}),
            ),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="A Generated Title"),
            ),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_desc_pub",
                body=new_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="new_conv_xyz",
            )

        published = [c.args[1] for c in sm.publish_chunk.call_args_list]
        desc_chunks = [
            c for c in published if c.startswith("data: ") and "conversation_description" in c
        ]
        assert desc_chunks, "expected a conversation_description SSE event"
        assert desc_chunks[-1].endswith("\n\n")
        assert json.loads(desc_chunks[-1][6:])["conversation_description"] == "A Generated Title"


# ===========================================================================
# _run_chat_stream — save ordering / cleanup
# ===========================================================================


@pytest.mark.unit
class TestRunChatStreamSaveAndCleanup:
    async def test_happy_path_saves_exactly_once(self, test_user, existing_conv_body):
        """Early save sets _saved=True so the finally fallback does NOT save again."""
        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(sm, agent_stream=_done_only_stream(), save_mock=save_mock):
            await run_chat_stream_background(
                stream_id="stream_once",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        assert save_mock.await_count == 1

    async def test_cleanup_and_deregister_always_run_on_success(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        with _run_stream_patches(sm, agent_stream=_done_only_stream()):
            await run_chat_stream_background(
                stream_id="stream_cleanup",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        sm.cleanup.assert_awaited_once_with("stream_cleanup")
        # in-process orchestration state for this stream is deregistered
        assert "stream_cleanup" not in inbox._executor_done_events
        assert inbox.get_tool_event_collector("stream_cleanup") is None

    async def test_tool_usage_telemetry_logged_in_finally(self, test_user, existing_conv_body):
        """The finally block records tool-usage telemetry (count + distinct tool names)
        derived from the accumulated tool_data. Kills the `tool_data.get("tool_data", [])`
        key, the `"tool_name" in e` membership and its In->NotIn flip."""

        async def agent():
            for name in ("search_results", "weather_data"):
                yield (
                    "data: "
                    + json.dumps({"tool_data": {"tool_name": name, "data": {}, "timestamp": "t"}})
                    + "\n\n"
                )
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        log_mock = MagicMock()
        log_mock.get.return_value = {}
        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch("app.utils.stream_utils.stream_manager", sm),
            patch("app.services.chat_service.call_agent", new=AsyncMock(return_value=agent())),
            patch("app.services.chat_service._save_conversation_async", new=AsyncMock()),
            patch("app.services.chat_service.UsageMetadataCallbackHandler", MagicMock()),
            patch("app.services.chat_service.log", log_mock),
        ):
            await run_chat_stream_background(
                stream_id="stream_telemetry",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        telemetry = next(
            c.kwargs for c in log_mock.set.call_args_list if "tool_calls_count" in c.kwargs
        )
        assert telemetry["tool_calls_count"] == 2
        assert set(telemetry["tool_types"]) == {"search_results", "weather_data"}


@pytest.mark.unit
class TestRunChatStreamErrorPath:
    async def test_error_chunk_published_before_set_error(self, test_user, existing_conv_body):
        """set_error sends STREAM_ERROR_SIGNAL which breaks the subscriber, so the
        human-readable error chunk MUST be published first."""
        sm = _make_stream_manager_mock()
        order: list[str] = []
        sm.publish_chunk = AsyncMock(side_effect=lambda sid, chunk: order.append(f"pub:{chunk}"))
        sm.set_error = AsyncMock(side_effect=lambda sid, err: order.append(f"err:{err}"))

        with _run_stream_patches(sm, agent_side_effect=RuntimeError("network timeout")):
            await run_chat_stream_background(
                stream_id="stream_err",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        error_pub_idx = next(
            i for i, e in enumerate(order) if e.startswith("pub:") and "network timeout" in e
        )
        set_err_idx = next(i for i, e in enumerate(order) if e.startswith("err:"))
        assert error_pub_idx < set_err_idx
        # the published error chunk is a well-formed SSE frame carrying the real message
        err_chunk = order[error_pub_idx][len("pub:") :]
        assert err_chunk.startswith("data: ")
        assert err_chunk.endswith("\n\n")
        assert json.loads(err_chunk[6:])["error"] == "network timeout"

    async def test_fallback_save_runs_when_early_save_never_reached(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        save_mock = AsyncMock()
        with _run_stream_patches(
            sm, agent_side_effect=RuntimeError("agent down"), save_mock=save_mock
        ):
            await run_chat_stream_background(
                stream_id="stream_fallback",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        # Agent failed before the early save => exactly the finally fallback save runs.
        save_mock.assert_awaited_once()
        sm.cleanup.assert_awaited_once_with("stream_fallback")


# ===========================================================================
# _run_chat_stream — executor wait + tool-data push
# ===========================================================================


@pytest.mark.unit
class TestRunChatStreamExecutorWait:
    async def test_executor_tool_data_pushed_to_mongo_with_correct_filter(
        self, test_user, existing_conv_body
    ):
        """When an executor was spawned, after it signals done its accumulated
        tool_data is $push-ed onto the bot message with the right filter."""
        sm = _make_stream_manager_mock()
        coll = MagicMock()
        coll.update_one = AsyncMock()
        executor_td = [{"tool_name": "tool_calls_data", "data": {}, "timestamp": "t"}]

        # _run_chat_stream registers its OWN executor-done event at the top of the
        # function, so it must be returned already-set or the wait_for hangs for 1800s.
        preset_event = asyncio.Event()
        preset_event.set()

        with _run_stream_patches(
            sm,
            patch("app.services.chat_service.conversations_collection", coll),
            patch("app.services.chat_service.was_executor_spawned", return_value=True),
            patch(
                "app.services.chat_service.register_executor_done_event",
                return_value=preset_event,
            ),
            patch(
                "app.services.chat_service._accumulate_executor_tool_data",
                return_value=executor_td,
            ),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_exec",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        coll.update_one.assert_awaited_once()
        filt, update = coll.update_one.call_args.args
        assert filt["user_id"] == "user_abc"
        assert filt["conversation_id"] == "conv_existing_123"
        assert "messages.message_id" in filt
        assert update["$push"]["messages.$.tool_data"]["$each"] == executor_td

    async def test_no_executor_push_when_not_spawned(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        coll = MagicMock()
        coll.update_one = AsyncMock()

        with _run_stream_patches(
            sm,
            patch("app.services.chat_service.conversations_collection", coll),
            patch("app.services.chat_service.was_executor_spawned", return_value=False),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_no_exec",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        coll.update_one.assert_not_called()

    async def test_no_executor_wait_when_cancelled_even_if_spawned(
        self, test_user, existing_conv_body
    ):
        """A cancelled stream must NOT wait for / push executor tool_data, even when an
        executor was spawned. Kills the `not is_cancelled` half of the wait guard."""
        sm = _make_stream_manager_mock(is_cancelled=True)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        accumulate = MagicMock(return_value=[{"tool_name": "x"}])

        with _run_stream_patches(
            sm,
            patch("app.services.chat_service.conversations_collection", coll),
            patch("app.services.chat_service.was_executor_spawned", return_value=True),
            patch("app.services.chat_service._accumulate_executor_tool_data", new=accumulate),
            agent_stream=_done_only_stream(),
        ):
            await run_chat_stream_background(
                stream_id="stream_cancel_exec",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(UTC),
                conversation_id="conv_existing_123",
            )

        accumulate.assert_not_called()
        coll.update_one.assert_not_called()


# ===========================================================================
# _start_description_task
# ===========================================================================


@pytest.mark.unit
class TestStartDescriptionTask:
    async def test_returns_none_for_existing_conversation(self, test_user, existing_conv_body):
        result = _start_description_task(
            is_new_conversation=False,
            body=existing_conv_body,
            conversation_id="c",
            user=test_user,
        )
        assert result is None

    async def test_spawns_description_task_with_last_message_for_new_conversation(self, test_user):
        body = MessageRequestWithHistory(
            message="m",
            messages=[
                {"role": "user", "content": "first"},
                {"role": "user", "content": "last"},
            ],
            conversation_id=None,
            selectedTool="search",
        )
        gen_mock = AsyncMock(return_value="desc")
        with patch("app.services.chat_service.generate_and_update_description", new=gen_mock):
            task = _start_description_task(
                is_new_conversation=True,
                body=body,
                conversation_id="conv_new",
                user=test_user,
            )
            assert task is not None
            await task

        gen_mock.assert_awaited_once()
        pos = gen_mock.call_args.args
        assert pos[0] == "conv_new"
        # The LAST message and the selected tool are forwarded for description generation.
        assert pos[1] == {"role": "user", "content": "last"}
        assert "search" in pos


# ===========================================================================
# _wait_for_http_subscriber
# ===========================================================================


@pytest.mark.unit
class TestWaitForHttpSubscriber:
    async def test_returns_immediately_when_no_event(self):
        # Must not raise / hang when there is no event to wait on.
        await _wait_for_http_subscriber(None, "sid")

    async def test_returns_immediately_when_event_already_set(self):
        ev = asyncio.Event()
        ev.set()
        with patch(
            "app.services.chat_service.asyncio.wait_for",
            new=AsyncMock(side_effect=AssertionError("must not wait on a set event")),
        ):
            await _wait_for_http_subscriber(ev, "sid")

    async def test_swallows_timeout_when_event_never_set(self):
        ev = asyncio.Event()  # never set
        with patch(
            "app.services.chat_service.asyncio.wait_for",
            new=AsyncMock(side_effect=TimeoutError),
        ):
            # Must proceed without raising.
            await _wait_for_http_subscriber(ev, "sid_timeout")


# ===========================================================================
# _initialize_new_conversation
# ===========================================================================


@pytest.mark.unit
class TestInitializeNewConversation:
    async def test_creates_conversation_and_builds_init_frame(self, test_user):
        body = MessageRequestWithHistory(
            message="hi",
            messages=[{"role": "user", "content": "hi"}],
            conversation_id=None,
            selectedTool="search",
        )
        create_mock = AsyncMock(return_value={"conversation_description": "My Conv"})
        with patch("app.services.chat_service.create_conversation", new=create_mock):
            frame = await _initialize_new_conversation(
                body=body,
                user=test_user,
                conversation_id="conv_init",
                user_message_id="umsg",
                bot_message_id="bmsg",
                stream_id="sid_init",
            )

        create_mock.assert_awaited_once()
        assert create_mock.call_args.args[0] == {"role": "user", "content": "hi"}
        assert create_mock.call_args.kwargs["selectedTool"] == "search"
        # Description is generated asynchronously later, NOT synchronously here.
        assert create_mock.call_args.kwargs["generate_description"] is False
        assert create_mock.call_args.kwargs["conversation_id"] == "conv_init"

        # SSE frame contract: "data: " prefix and a trailing blank-line "\n\n" terminator.
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame[6:])
        assert payload["conversation_id"] == "conv_init"
        assert payload["conversation_description"] == "My Conv"
        assert payload["user_message_id"] == "umsg"
        assert payload["bot_message_id"] == "bmsg"
        assert payload["stream_id"] == "sid_init"


# ===========================================================================
# _save_conversation_async
# ===========================================================================


@pytest.mark.unit
class TestSaveConversationAsync:
    async def test_saves_user_then_bot_message_with_conversation_id(self, test_user):
        body = MessageRequestWithHistory(
            message="ignored fallback",
            messages=[{"role": "user", "content": "Hello"}],
            conversation_id="conv",
        )
        update_mock = AsyncMock()
        with (
            patch("app.services.chat_service.update_messages", new=update_mock),
            patch("app.services.chat_service._process_token_usage_and_cost", new=AsyncMock()),
        ):
            await _save_conversation_async(
                body=body,
                user=test_user,
                conversation_id="conv_specific",
                complete_message="The answer is 42.",
                tool_data={"tool_data": [{"tool_name": "x"}]},
                metadata={},
                user_message_id="umsg_1",
                bot_message_id="bmsg_1",
            )

        req = update_mock.call_args.args[0]
        assert req.conversation_id == "conv_specific"
        assert len(req.messages) == 2
        user_msg, bot_msg = req.messages
        assert user_msg.type == "user"
        assert user_msg.response == "Hello"
        assert user_msg.message_id == "umsg_1"
        assert bot_msg.type == "bot"
        assert bot_msg.response == "The answer is 42."
        assert bot_msg.message_id == "bmsg_1"
        # tool_data keys are applied onto the bot message.
        assert bot_msg.tool_data == [{"tool_name": "x"}]
        # The user message is timestamped exactly 100ms BEFORE the bot reply so it sorts
        # first in the conversation. Assert the precise gap (kills the 100 -> 101 mutant).
        user_dt = datetime.fromisoformat(user_msg.date)
        bot_dt = datetime.fromisoformat(bot_msg.date)
        assert bot_dt - user_dt == timedelta(milliseconds=100)

    async def test_user_content_falls_back_to_body_message_when_no_history(self, test_user):
        body = MessageRequestWithHistory(
            message="Fallback content",
            messages=[],
            conversation_id="conv",
        )
        update_mock = AsyncMock()
        with (
            patch("app.services.chat_service.update_messages", new=update_mock),
            patch("app.services.chat_service._process_token_usage_and_cost", new=AsyncMock()),
        ):
            await _save_conversation_async(
                body=body,
                user=test_user,
                conversation_id="conv",
                complete_message="resp",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )

        assert update_mock.call_args.args[0].messages[0].response == "Fallback content"

    async def test_token_processing_called_only_when_metadata_present(
        self, test_user, new_conv_body
    ):
        token_mock = AsyncMock()
        metadata = {"claude-3-5-sonnet": {"input_tokens": 100, "output_tokens": 50}}
        with (
            patch("app.services.chat_service.update_messages", new=AsyncMock()),
            patch("app.services.chat_service._process_token_usage_and_cost", new=token_mock),
        ):
            await _save_conversation_async(
                body=new_conv_body,
                user=test_user,
                conversation_id="conv",
                complete_message="ok",
                tool_data={},
                metadata=metadata,
                user_message_id="u",
                bot_message_id="b",
            )

        token_mock.assert_awaited_once_with("user_abc", metadata)

    async def test_token_processing_skipped_when_metadata_empty(self, test_user, new_conv_body):
        token_mock = AsyncMock()
        with (
            patch("app.services.chat_service.update_messages", new=AsyncMock()),
            patch("app.services.chat_service._process_token_usage_and_cost", new=token_mock),
        ):
            await _save_conversation_async(
                body=new_conv_body,
                user=test_user,
                conversation_id="conv",
                complete_message="ok",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )

        token_mock.assert_not_called()

    async def test_token_processing_failure_does_not_block_save(self, test_user, new_conv_body):
        update_mock = AsyncMock()
        with (
            patch("app.services.chat_service.update_messages", new=update_mock),
            patch(
                "app.services.chat_service._process_token_usage_and_cost",
                new=AsyncMock(side_effect=Exception("payment down")),
            ),
        ):
            await _save_conversation_async(
                body=new_conv_body,
                user=test_user,
                conversation_id="conv",
                complete_message="ok",
                tool_data={},
                metadata={"model": {"input_tokens": 10, "output_tokens": 5}},
                user_message_id="u",
                bot_message_id="b",
            )

        update_mock.assert_awaited_once()


# ===========================================================================
# _accumulate_executor_tool_data
# ===========================================================================


@pytest.mark.unit
class TestAccumulateExecutorToolData:
    def test_returns_empty_list_when_no_collector(self):
        # No collector registered for this stream id.
        assert _accumulate_executor_tool_data("stream_absent") == []

    def test_backfills_tool_calls_data_output_from_collector(self):
        sid = "stream_acc"
        collector = inbox.register_tool_event_collector(sid)
        collector.append(
            {
                "tool_data": {
                    "tool_name": "tool_calls_data",
                    "data": {"tool_call_id": "c1", "name": "search"},
                    "timestamp": "t",
                }
            }
        )
        collector.append({"tool_output": {"tool_call_id": "c1", "output": "the result"}})

        result = _accumulate_executor_tool_data(sid)

        entry = next(e for e in result if e["tool_name"] == "tool_calls_data")
        assert entry["data"]["output"] == "the result"


# ===========================================================================
# _process_token_usage_and_cost
# ===========================================================================


def _subscription(plan: str = "free") -> MagicMock:
    sub = MagicMock()
    sub.plan_type = plan
    return sub


@pytest.mark.unit
class TestProcessTokenUsageAndCost:
    async def test_costs_summed_and_limiter_incremented_with_credits(self):
        metadata = {
            "model-a": {
                "input_tokens": 100,
                "output_tokens": 50,
                "input_token_details": {"cache_read": 20},
            }
        }
        calc_mock = AsyncMock(return_value={"total_cost": 0.0042})
        limiter_mock = AsyncMock()
        log_mock = MagicMock()
        log_mock.get.return_value = {}
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
            patch("app.services.chat_service.log", log_mock),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        # cached_tokens taken from input_token_details.cache_read
        assert calc_mock.call_args.kwargs["cached_tokens"] == 20
        assert calc_mock.call_args.args == ("model-a", 100, 50)
        # the limiter is charged the summed credits
        limiter_mock.assert_awaited_once()
        assert limiter_mock.call_args.kwargs["credits_used"] == 0.0042
        assert limiter_mock.call_args.kwargs["feature_key"] == "chat_messages"
        assert limiter_mock.call_args.kwargs["user_id"] == "user_x"
        # the caller's plan is forwarded so the limiter applies the right tier
        assert limiter_mock.call_args.kwargs["user_plan"] == "free"
        # the billed cost is recorded on the wide-event model context (billing audit).
        model_logged = log_mock.set.call_args.kwargs["model"]
        assert model_logged["cost_usd"] == 0.0042

    async def test_limiter_not_incremented_when_zero_credits(self):
        metadata = {"model-a": {"input_tokens": 100, "output_tokens": 50}}
        calc_mock = AsyncMock(return_value={"total_cost": 0.0})
        limiter_mock = AsyncMock()
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        calc_mock.assert_awaited_once()
        limiter_mock.assert_not_called()

    async def test_zero_token_entry_is_not_priced(self):
        metadata = {"empty-model": {"input_tokens": 0, "output_tokens": 0}}
        calc_mock = AsyncMock(return_value={"total_cost": 1.0})
        limiter_mock = AsyncMock()
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        calc_mock.assert_not_called()
        limiter_mock.assert_not_called()

    async def test_output_only_entry_is_still_priced(self):
        """An entry with input_tokens==0 but a single output token must still be billed.
        output_tokens==1 is the boundary that kills BOTH the `or` -> `and` boolop AND the
        `output_tokens > 0` -> `> 1` const mutant (1 > 1 is False)."""
        metadata = {"model-out": {"input_tokens": 0, "output_tokens": 1}}
        calc_mock = AsyncMock(return_value={"total_cost": 0.001})
        limiter_mock = AsyncMock()
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        calc_mock.assert_awaited_once()
        assert calc_mock.call_args.args == ("model-out", 0, 1)
        limiter_mock.assert_awaited_once()

    async def test_cached_tokens_fall_back_to_cached_content_token_count(self):
        """When input_token_details.cache_read is absent, cached_tokens falls back to
        the provider's cached_content_token_count. Kills the second `or` in the chain."""
        metadata = {
            "model-g": {
                "input_tokens": 100,
                "output_tokens": 0,
                "cached_content_token_count": 40,
            }
        }
        calc_mock = AsyncMock(return_value={"total_cost": 0.002})
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        assert calc_mock.call_args.kwargs["cached_tokens"] == 40

    async def test_cached_tokens_default_to_zero_when_no_cache_info(self):
        """A model entry with no cache fields bills zero cached tokens (the final
        `or 0` in the fallback chain). Kills const 0 -> 1 on that branch."""
        metadata = {"model-h": {"input_tokens": 100, "output_tokens": 10}}
        calc_mock = AsyncMock(return_value={"total_cost": 0.003})
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        assert calc_mock.call_args.kwargs["cached_tokens"] == 0

    async def test_entry_missing_token_keys_defaults_to_zero_and_is_skipped(self):
        """A model entry with NO input/output token keys defaults both to 0 and is not
        priced. Kills the `.get("input_tokens", 0)` / output default 0 -> 1 mutants
        (which would make a key-less entry look billable)."""
        metadata = {"model-empty": {"some_other_field": "x"}}
        calc_mock = AsyncMock(return_value={"total_cost": 5.0})
        limiter_mock = AsyncMock()
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        calc_mock.assert_not_called()
        limiter_mock.assert_not_called()

    async def test_single_input_token_is_priced(self):
        """An entry with input_tokens==1, output_tokens==0 must still be priced. Kills
        the `> 0` -> `> 1` const mutants on the billable-entry guard."""
        metadata = {"model-one": {"input_tokens": 1, "output_tokens": 0}}
        calc_mock = AsyncMock(return_value={"total_cost": 0.00001})
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription("free")),
            ),
            patch("app.services.chat_service.calculate_token_cost", new=calc_mock),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        calc_mock.assert_awaited_once()
        assert calc_mock.call_args.args == ("model-one", 1, 0)

    async def test_user_plan_defaults_to_free_when_subscription_has_no_plan(self):
        """When the subscription's plan_type is falsy, the limiter is charged with
        PlanType.FREE. Kills the `subscription.plan_type or PlanType.FREE` boolop."""
        metadata = {"model-a": {"input_tokens": 10, "output_tokens": 5}}
        limiter_mock = AsyncMock()
        with (
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=_subscription(None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.01}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=limiter_mock,
            ),
        ):
            await _process_token_usage_and_cost("user_x", metadata)

        limiter_mock.assert_awaited_once()
        assert limiter_mock.call_args.kwargs["user_plan"] == PlanType.FREE

    async def test_exception_is_swallowed(self):
        with patch(
            "app.services.chat_service.payment_service.get_user_subscription_status",
            new=AsyncMock(side_effect=Exception("subscription service down")),
        ):
            # Must not raise.
            await _process_token_usage_and_cost("user_x", {"m": {"input_tokens": 1}})
