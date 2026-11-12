"""Ask the model again when it answered with nothing at all.

A comms turn can come back with no content (reasoning only, bare message breaks,
a content filter, a dropped body), which stream.py turns into a fixed apology.
A reply streaming only breaks is stopped at MAX_LEADING_MESSAGE_BREAKS instead
of running to the output limit, and counts as empty too.

Innermost in the comms wrap_model_call chain; repeats the call ONCE. NOT retried:
errors (they own the turn's error path), cancellations and tool calls. The retry
drops the breaks-only replies the model may be copying and adds one notice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
import time
from typing import NamedTuple
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, GenerationChunk
from langchain_core.tracers.context import register_configure_hook

from app.constants.chat import EMPTY_COMPLETION_RETRY_NOTICE, MAX_LEADING_MESSAGE_BREAKS
from app.constants.log_tags import LogTag
from app.utils.message_breaks import (
    count_message_breaks,
    is_only_message_breaks,
    split_message_bubbles,
    strip_edge_message_breaks,
)
from app.utils.multimodal import MessageContent, extract_text_content
from shared.py.wide_events import log

ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]


class RunawayMessageBreaksError(Exception):
    """A model call streamed only bubble breaks past the bound, and was stopped."""

    def __init__(self, *, breaks: int, chars: int, message_id: str | None) -> None:
        super().__init__(f"model streamed {breaks} bubble breaks and no text")
        self.breaks = breaks
        self.chars = chars
        self.message_id = message_id


class RunawayBreaksGuard(AsyncCallbackHandler):
    """Stop a streaming model call whose reply is still nothing but breaks past the bound."""

    raise_error = True
    run_inline = True

    def __init__(self) -> None:
        # None once a run has streamed real text: it is a reply, and no longer watched.
        self._text_by_run: dict[UUID, str | None] = {}

    async def on_llm_new_token(
        self,
        token: str | list[str | dict[str, object]],
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,
        run_id: UUID,
        # The callback contract also passes parent_run_id and tags; this reads neither.
        **_kwargs: object,
    ) -> None:
        """Raise RunawayMessageBreaksError once this run's breaks-only text passes the bound."""
        so_far = self._text_by_run.get(run_id, "")
        if so_far is None:
            return
        text = so_far + (chunk.text if chunk is not None else extract_text_content(token))
        if not is_only_message_breaks(text):
            self._text_by_run[run_id] = None
            return
        self._text_by_run[run_id] = text
        breaks = count_message_breaks(text)
        if breaks > MAX_LEADING_MESSAGE_BREAKS:
            message_id = chunk.message.id if isinstance(chunk, ChatGenerationChunk) else None
            raise RunawayMessageBreaksError(breaks=breaks, chars=len(text), message_id=message_id)


# A model call configured while this is set carries the guard: the comms model
# is invoked through a partial whose callbacks this middleware cannot reach.
_ACTIVE_GUARD: ContextVar[RunawayBreaksGuard | None] = ContextVar(
    "runaway_breaks_guard", default=None
)
register_configure_hook(_ACTIVE_GUARD, inheritable=True)


def _is_contentless(message: AIMessage) -> bool:
    return not message.tool_calls and not split_message_bubbles(
        extract_text_content(message.content)
    )


def is_empty_completion(response: ModelResponse) -> bool:
    """Return whether the model returned nothing a user or the graph can use.

    Empty means: no message at all, or an AIMessage with no tool calls and
    no bubble with text (whitespace and bare message breaks are nothing). A non-AI result is left alone — this seam only
    judges the model's own output.
    """
    message = response.result[0] if response.result else None
    if message is None:
        return True
    if not isinstance(message, AIMessage):
        return False
    return _is_contentless(message)


def _without_edge_breaks(content: MessageContent) -> MessageContent:
    if isinstance(content, str):
        return strip_edge_message_breaks(content)
    return [
        {**block, "text": strip_edge_message_breaks(block["text"])}
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        else block
        for block in content
    ]


def _retry_history(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Drop the breaks-only replies a model copies, and trim the break runs at reply edges."""
    history: list[AnyMessage] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            history.append(message)
        elif not _is_contentless(message):
            content = _without_edge_breaks(message.content)
            changed = content != message.content
            history.append(message.model_copy(update={"content": content}) if changed else message)
    return history


class _Attempt(NamedTuple):
    response: ModelResponse
    stopped: bool


async def _guarded_call(request: ModelRequest, handler: ModelCallHandler) -> _Attempt:
    """Call the model under a runaway-breaks guard; a stopped call answers with an empty message."""
    started = time.monotonic()
    guard = _ACTIVE_GUARD.set(RunawayBreaksGuard())
    try:
        return _Attempt(await handler(request), stopped=False)
    except RunawayMessageBreaksError as runaway:
        log.warning(
            f"{LogTag.AGENT} Model streamed only message breaks; stopped the call",
            agent_name="comms_agent",
            runaway_breaks=runaway.breaks,
            runaway_chars=runaway.chars,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
        )
        # The streamed attempt's id: LangGraph re-emits a node's output message
        # under any id it has not streamed, which would show the stored placeholder.
        stopped = AIMessage(content="", id=runaway.message_id)
        return _Attempt(ModelResponse(result=[stopped]), stopped=True)
    finally:
        _ACTIVE_GUARD.reset(guard)


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
        """Call the model; on an empty completion, retry once without the poisoned history."""
        first = await _guarded_call(request, handler)
        if not is_empty_completion(first.response):
            return first.response

        history = _retry_history(request.messages)
        log.warning(
            f"{LogTag.AGENT} Empty completion, retrying the model call once",
            agent_name="comms_agent",
            retry_dropped_messages=len(request.messages) - len(history),
        )
        retry_request = request.override(
            messages=[*history, HumanMessage(content=EMPTY_COMPLETION_RETRY_NOTICE)]
        )
        retry = await _guarded_call(retry_request, handler)
        recovered = not is_empty_completion(retry.response)
        # Flat on the turn: this is a property of the turn the user lived
        # through, not of a sub-scope, and it has to be countable next to
        # ``empty_completion_reason`` on the same event.
        log.set(
            retried_empty_completion=True,
            empty_completion_retry_recovered=recovered,
            empty_completion_runaway_stops=sum((first.stopped, retry.stopped)),
        )
        if recovered:
            return retry.response
        log.error(
            f"{LogTag.AGENT} Empty completion survived the retry",
            agent_name="comms_agent",
        )
        return retry.response
