"""A comms reply streaming nothing but bubble breaks is stopped at a small bound.

In production a reply of 3,998 bare breaks ran ~100 s to the output limit before
anything noticed. The guard reads the same token callbacks the chat stream does;
these tests feed it tokens directly, and test_chat_stream.py proves it is wired
into a real comms graph run.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
import pytest

from app.agents.middleware.empty_completion import (
    EmptyCompletionRetryMiddleware,
    RunawayBreaksGuard,
    RunawayMessageBreaksError,
)
from app.constants.chat import EMPTY_COMPLETION_RETRY_NOTICE, MAX_LEADING_MESSAGE_BREAKS
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag

ANSWER = AIMessage(content="you have two meetings.")


async def _stream(guard: RunawayBreaksGuard, tokens: list[str]) -> None:
    """Stream tokens through the guard as one model call."""
    run = uuid4()
    for token in tokens:
        await guard.on_llm_new_token(token, run_id=run)


def _request() -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=[HumanMessage(content="what's on my calendar?")],
        system_message=None,
        tools=[],
        state={"messages": []},
        runtime=MagicMock(),
    )


class TestTheGuardStopsARunawayAtTheBound:
    async def test_the_bound_itself_is_still_allowed(self):
        await _stream(RunawayBreaksGuard(), [NEW_MESSAGE_BREAKER] * MAX_LEADING_MESSAGE_BREAKS)

    async def test_one_break_past_the_bound_stops_the_call(self):
        with pytest.raises(RunawayMessageBreaksError) as stopped:
            await _stream(
                RunawayBreaksGuard(), [NEW_MESSAGE_BREAKER] * (MAX_LEADING_MESSAGE_BREAKS + 1)
            )

        assert stopped.value.breaks == MAX_LEADING_MESSAGE_BREAKS + 1
        assert stopped.value.chars == len(NEW_MESSAGE_BREAKER) * (MAX_LEADING_MESSAGE_BREAKS + 1)
        assert str(stopped.value) == (
            f"model streamed {MAX_LEADING_MESSAGE_BREAKS + 1} bubble breaks and no text"
        )

    async def test_block_tokens_with_no_chunk_still_count(self):
        """A model that streams list content without a chunk passes its blocks as the token."""
        guard = RunawayBreaksGuard()
        run = uuid4()
        block: list[str | dict[str, object]] = [{"type": "text", "text": NEW_MESSAGE_BREAKER}]
        for _ in range(MAX_LEADING_MESSAGE_BREAKS):
            await guard.on_llm_new_token(block, run_id=run)

        with pytest.raises(RunawayMessageBreaksError):
            await guard.on_llm_new_token(block, run_id=run)

    async def test_breaks_split_across_tokens_still_count(self):
        """A provider streams a sentinel as "<", "NEW", "_MESSAGE", ...; a lone "<" must not read as text."""
        pieces = ["<", "NEW", "_MESSAGE", "_BREAK", ">", "\n"]

        with pytest.raises(RunawayMessageBreaksError):
            await _stream(RunawayBreaksGuard(), pieces * (MAX_LEADING_MESSAGE_BREAKS + 1))

    async def test_each_model_call_is_counted_on_its_own(self):
        """A provider retry or failover streams under its own run; half a runaway each is no runaway."""
        guard = RunawayBreaksGuard()
        half = [NEW_MESSAGE_BREAKER] * (MAX_LEADING_MESSAGE_BREAKS // 2 + 1)

        await _stream(guard, half)
        await _stream(guard, half)


class TestARealReplyIsNeverStopped:
    async def test_two_stray_breaks_then_text_stream_to_the_end(self):
        tokens = [NEW_MESSAGE_BREAKER, NEW_MESSAGE_BREAKER, "hey", "!"]

        await _stream(RunawayBreaksGuard(), tokens + [NEW_MESSAGE_BREAKER] * 50)

    async def test_a_long_multi_bubble_reply_streams_to_the_end(self):
        bubbles = [f"point {index}" for index in range(MAX_LEADING_MESSAGE_BREAKS * 2)]

        await _stream(RunawayBreaksGuard(), list(NEW_MESSAGE_BREAKER.join(bubbles)))


class TestAStoppedCallIsAnEmptyCompletion:
    async def test_a_stopped_call_is_retried_and_the_retry_answers(self):
        calls: list[ModelRequest] = []

        async def runaway_then_answer(request: ModelRequest) -> ModelResponse:
            calls.append(request)
            if len(calls) == 1:
                raise RunawayMessageBreaksError(breaks=9, chars=171, message_id=None)
            return ModelResponse(result=[ANSWER])

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(
            _request(), runaway_then_answer
        )

        assert len(calls) == 2
        assert response.result == [ANSWER]

    async def test_two_stopped_calls_answer_with_an_empty_message_not_an_error(self):
        """The middleware chain falls back to an unguarded direct call on any error; a stop must never reach it."""
        calls: list[ModelRequest] = []

        async def always_runaway(request: ModelRequest) -> ModelResponse:
            calls.append(request)
            raise RunawayMessageBreaksError(breaks=9, chars=171, message_id="m-1")

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(
            _request(), always_runaway
        )

        assert len(calls) == 2
        [message] = response.result
        assert isinstance(message, AIMessage)
        assert message.content == ""
        assert message.id == "m-1"

    async def test_a_real_streaming_model_call_is_stopped_by_the_guard(self):
        """The guard reaches the model through a configure hook, not through the handler's callbacks."""
        runaway = " ".join([NEW_MESSAGE_BREAKER] * 4000)
        model = GenericFakeChatModel(messages=iter([AIMessage(content=runaway), ANSWER]))

        async def stream_the_model(request: ModelRequest) -> ModelResponse:
            chunks = [chunk async for chunk in model.astream(request.messages)]
            return ModelResponse(result=[AIMessage(content="".join(c.text for c in chunks))])

        with patch("app.agents.middleware.empty_completion.log") as log:
            response = await EmptyCompletionRetryMiddleware().awrap_model_call(
                _request(), stream_the_model
            )

        assert log.set.call_args.kwargs["empty_completion_runaway_stops"] == 1
        assert [message.text for message in response.result] == [ANSWER.text]

    async def test_the_stopped_message_keeps_the_id_it_streamed_under(self):
        """LangGraph re-emits a node's output under an unstreamed id, which would show the user a placeholder."""
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=NEW_MESSAGE_BREAKER, id="m-1"))
        guard = RunawayBreaksGuard()
        run = uuid4()
        for _ in range(MAX_LEADING_MESSAGE_BREAKS):
            await guard.on_llm_new_token(NEW_MESSAGE_BREAKER, chunk=chunk, run_id=run)

        with pytest.raises(RunawayMessageBreaksError) as stopped:
            await guard.on_llm_new_token(NEW_MESSAGE_BREAKER, chunk=chunk, run_id=run)

        assert stopped.value.message_id == "m-1"

    async def test_a_stop_is_logged_with_what_it_saw_and_counted_on_the_turn(self):
        async def runaway_then_answer(request: ModelRequest) -> ModelResponse:
            if request.messages[-1].content != EMPTY_COMPLETION_RETRY_NOTICE:
                raise RunawayMessageBreaksError(breaks=9, chars=171, message_id=None)
            return ModelResponse(result=[ANSWER])

        clock = MagicMock()
        clock.monotonic.side_effect = [10.0, 10.0123456, 20.0, 20.0]
        with (
            patch("app.agents.middleware.empty_completion.log") as log,
            patch("app.agents.middleware.empty_completion.time", clock),
        ):
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), runaway_then_answer)

        stop = log.warning.call_args_list[0]
        assert stop.args == (
            f"{LogTag.AGENT} Model streamed only message breaks; stopped the call",
        )
        assert stop.kwargs == {
            "agent_name": "comms_agent",
            "runaway_breaks": 9,
            "runaway_chars": 171,
            "elapsed_ms": 12.35,
        }
        assert log.set.call_args.kwargs["empty_completion_runaway_stops"] == 1


class TestTheRetryNotice:
    async def test_the_retry_ends_with_the_notice_and_nothing_else_is_added(self):
        requests: list[ModelRequest] = []

        async def empty_then_answer(request: ModelRequest) -> ModelResponse:
            requests.append(request)
            return ModelResponse(result=[AIMessage(content="") if len(requests) == 1 else ANSWER])

        await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), empty_then_answer)

        assert requests[1].messages == [
            *requests[0].messages,
            HumanMessage(content=EMPTY_COMPLETION_RETRY_NOTICE),
        ]
