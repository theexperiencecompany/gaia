"""Ask the model again when it answered with nothing at all.

A comms turn can come back with no content — reasoning-only output, max_tokens
spent before the first token, a content filter, a dropped body — which
downstream treats as a real answer and turns into a fixed apology
(_substitute_empty_completion in app/services/chat/stream.py).

Sits innermost in the comms wrap_model_call chain and repeats the call ONCE
(an empty completion is a one-shot failure, not something that converges over
rounds). NOT retried: errors (already own the turn's error path),
cancellations (raise CancelledError instead of an empty message), and tool
calls (content of its own). Nothing streamed, so nothing needs retracting.
If the retry is also empty, the turn falls through to the existing honest line.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from app.constants.log_tags import LogTag
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]


def is_empty_completion(response: ModelResponse) -> bool:
    """Return whether the model returned nothing a user or the graph can use.

    Empty means: no message at all, or an AIMessage with no tool calls and
    no non-whitespace text. A non-AI result is left alone — this seam only
    judges the model's own output.
    """
    message = response.result[0] if response.result else None
    if message is None:
        return True
    if not isinstance(message, AIMessage):
        return False
    if message.tool_calls:
        return False
    return not extract_text_content(message.content).strip()


class EmptyCompletionRetryMiddleware(AgentMiddleware):
    """Retry the model call once when the completion is genuinely empty.

    Comms tier only — registered by create_comms_middleware. The executor's
    empty turn is read by comms, which can act on it; a user's empty turn is
    read by a person, who cannot.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: ModelCallHandler,
    ) -> ModelResponse:
        response = await handler(request)
        if not is_empty_completion(response):
            return response

        log.warning(
            f"{LogTag.AGENT} Empty completion, retrying the model call once",
            agent_name="comms_agent",
        )
        retry = await handler(request)
        recovered = not is_empty_completion(retry)
        # Flat on the turn: this is a property of the turn the user lived
        # through, not of a sub-scope, and it has to be countable next to
        # ``empty_completion_reason`` on the same event.
        log.set(retried_empty_completion=True, empty_completion_retry_recovered=recovered)
        if not recovered:
            log.error(
                f"{LogTag.AGENT} Empty completion survived the retry",
                agent_name="comms_agent",
            )
        return retry
