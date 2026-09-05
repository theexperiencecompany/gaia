"""StreamCancellationSafeCallbackHandler: stream cancellations are not errors.

Regression anchor: a normal chat-stream cancellation (client closed the stream,
or the ``ainvoke_llm`` wall-clock ceiling expired) raises ``asyncio.CancelledError``
or ``GeneratorExit`` at the run's yield point. The base PostHog LangChain callback
reports every ``on_*_error`` to error tracking, so these clean exits surfaced as
CancelledError/GeneratorExit crashes — one per nested runnable level. The handler
now drops those two lifecycle types while letting genuine LLM failures report.
"""

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config.posthog import StreamCancellationSafeCallbackHandler


@pytest.fixture
def handler() -> StreamCancellationSafeCallbackHandler:
    return StreamCancellationSafeCallbackHandler(client=MagicMock())


# Each error hook and the base capture method it delegates into.
_ERROR_HOOKS = [
    ("on_llm_error", "_capture_generation_run"),
    ("on_chain_error", "_capture_trace_or_span_run"),
    ("on_tool_error", "_capture_trace_or_span_run"),
    ("on_retriever_error", "_capture_trace_or_span_run"),
]


@pytest.mark.unit
@pytest.mark.parametrize(("hook", "capture_method"), _ERROR_HOOKS)
@pytest.mark.parametrize("error", [asyncio.CancelledError(), GeneratorExit()])
def test_stream_cancellation_is_not_reported(
    handler: StreamCancellationSafeCallbackHandler,
    hook: str,
    capture_method: str,
    error: BaseException,
) -> None:
    capture = MagicMock()
    setattr(handler, capture_method, capture)

    getattr(handler, hook)(error, run_id=uuid4())

    capture.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(("hook", "capture_method"), _ERROR_HOOKS)
def test_genuine_failure_is_still_reported(
    handler: StreamCancellationSafeCallbackHandler,
    hook: str,
    capture_method: str,
) -> None:
    capture = MagicMock()
    setattr(handler, capture_method, capture)

    getattr(handler, hook)(ValueError("model exploded"), run_id=uuid4())

    capture.assert_called_once()
