"""A model that answers with nothing is asked again, once.

41 empty bot messages across 14 production conversations reached persistence
with no text, no error and no cancellation. The turn-level recovery was a fixed
apology asking the user to retype their message — recovery in the wrong layer:
the model call is what failed. These tests drive the real middleware against a
scripted handler, the same seam ``MiddlewareExecutor.wrap_model_invocation``
builds in production; the model is the only thing faked, because a real model
cannot be made to return nothing on demand.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.middleware.empty_completion import (
    EmptyCompletionRetryMiddleware,
    is_empty_completion,
)
from app.constants.log_tags import LogTag

EMPTY = AIMessage(content="")
WHITESPACE = AIMessage(content="\n  \n")
ANSWER = AIMessage(content="you have two meetings.")
TOOL_CALL = AIMessage(
    content="",
    tool_calls=[{"name": "call_executor", "args": {"task": "check"}, "id": "tc-1"}],
)


def _request() -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=[HumanMessage(content="what's on my calendar?")],
        system_message=None,
        tools=[],
        state={"messages": []},
        runtime=MagicMock(),
    )


class _ScriptedHandler:
    """Returns the next scripted message per call, recording every request."""

    def __init__(self, *messages: AIMessage) -> None:
        self._messages = list(messages)
        self.requests: list[ModelRequest] = []

    async def __call__(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            result=[self._messages[min(len(self.requests) - 1, len(self._messages) - 1)]]
        )


class TestAnEmptyCompletionIsRetriedOnce:
    async def test_a_contentless_reply_is_asked_again_and_the_second_answer_wins(self):
        handler = _ScriptedHandler(EMPTY, ANSWER)

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 2
        assert response.result == [ANSWER]

    async def test_a_whitespace_only_reply_counts_as_empty(self):
        """Every renderer drops a whitespace body exactly like an empty one."""
        handler = _ScriptedHandler(WHITESPACE, ANSWER)

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 2
        assert response.result == [ANSWER]

    async def test_the_retry_asks_the_same_question_unchanged(self):
        """Nothing about the request was wrong, so nothing is appended to it —
        a correction note here would teach the model that silence was a turn."""
        handler = _ScriptedHandler(EMPTY, ANSWER)

        await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert handler.requests[1].messages == handler.requests[0].messages

    async def test_the_retry_is_bounded_to_one_call(self):
        """The second call is charged to the user like any other."""
        handler = _ScriptedHandler(EMPTY)

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 2
        assert response.result == [EMPTY]


class TestOnlyGenuineSilenceIsRetried:
    async def test_a_real_answer_is_returned_on_the_first_call(self):
        handler = _ScriptedHandler(ANSWER)

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1
        assert response.result == [ANSWER]

    async def test_a_tool_call_with_no_prose_is_content_and_is_left_alone(self):
        """A card, a connect frame or a delegation is the model acting. Retrying
        it would run the same tool twice."""
        handler = _ScriptedHandler(TOOL_CALL)

        response = await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1
        assert response.result == [TOOL_CALL]

    async def test_a_failed_call_raises_through_and_is_never_retried(self):
        """The turn's error path owns a failure; a second call would double the
        latency the user waits through before seeing the error."""
        calls: list[ModelRequest] = []

        async def failing(request: ModelRequest) -> ModelResponse:
            calls.append(request)
            raise TimeoutError("provider timed out")

        try:
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), failing)
        except TimeoutError:
            pass
        else:  # pragma: no cover - the raise is the behaviour under test
            raise AssertionError("the provider error was swallowed")

        assert len(calls) == 1

    async def test_a_cancelled_call_is_never_retried(self):
        """A user stop cancels this task: the retry must not resurrect the turn
        the user just stopped paying for."""
        calls: list[ModelRequest] = []

        async def cancelled(request: ModelRequest) -> ModelResponse:
            calls.append(request)
            raise asyncio.CancelledError()

        try:
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), cancelled)
        except asyncio.CancelledError:
            pass
        else:  # pragma: no cover - the raise is the behaviour under test
            raise AssertionError("the cancellation was swallowed")

        assert len(calls) == 1


class TestTheRetryIsRecordedOnTheTurn:
    """One retried turn is indistinguishable from an ordinary one in the
    conversation, so the wide event is the only place this is countable."""

    async def _fields(self, handler: _ScriptedHandler) -> dict[str, Any]:
        with patch("app.agents.middleware.empty_completion.log") as mock_log:
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)
            return dict(mock_log.set.call_args.kwargs) if mock_log.set.call_args else {}

    async def test_a_recovered_turn_is_recorded_as_retried_and_recovered(self):
        fields = await self._fields(_ScriptedHandler(EMPTY, ANSWER))

        assert fields == {
            "retried_empty_completion": True,
            "empty_completion_retry_recovered": True,
        }

    async def test_a_turn_still_empty_after_the_retry_is_recorded_as_unrecovered(self):
        fields = await self._fields(_ScriptedHandler(EMPTY))

        assert fields == {
            "retried_empty_completion": True,
            "empty_completion_retry_recovered": False,
        }

    async def test_an_ordinary_turn_records_nothing(self):
        """The flag must mean "this happened", so it is absent, not False, on
        every turn that never went silent."""
        fields = await self._fields(_ScriptedHandler(ANSWER))

        assert fields == {}

    async def test_silence_surviving_the_retry_is_logged_as_an_error(self):
        handler = _ScriptedHandler(EMPTY)

        with patch("app.agents.middleware.empty_completion.log") as mock_log:
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        assert mock_log.error.call_args.args == (
            f"{LogTag.AGENT} Empty completion survived the retry",
        )


class TestWhatCountsAsEmpty:
    def test_no_message_at_all_is_empty(self):
        assert is_empty_completion(ModelResponse(result=[])) is True

    def test_a_message_that_is_not_the_models_own_is_left_alone(self):
        assert is_empty_completion(ModelResponse(result=[HumanMessage(content="")])) is False


class TestTheRetryIsLoggedExactly:
    async def test_the_retry_and_the_surviving_silence_are_logged_against_comms(self):
        handler = _ScriptedHandler(EMPTY)
        with patch("app.agents.middleware.empty_completion.log") as log:
            await EmptyCompletionRetryMiddleware().awrap_model_call(_request(), handler)

        log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Empty completion, retrying the model call once",
            agent_name="comms_agent",
        )
        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Empty completion survived the retry",
            agent_name="comms_agent",
        )
