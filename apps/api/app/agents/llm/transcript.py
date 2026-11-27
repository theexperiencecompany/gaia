"""Shape a message list the way every provider accepts tool use, right before it is sent.

The invariant every provider enforces (OpenAI and Anthropic reject the request, Workers AI
tolerates it): each assistant tool call is followed, in the messages right after it, by
exactly one result per call; no tool result stands without its call. A thread breaks it
whenever a result is written after later turns (a backfill appended by the messages
reducer), a run stops mid tool call, or a middleware drops or folds part of the history.
This module is the one owner of that rule; the checkpoint is never rewritten for it.
"""

from collections.abc import Sequence
from typing import cast

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    InvalidToolCall,
    ToolCall,
    ToolMessage,
    convert_to_messages,
)

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

UNFINISHED_TOOL_RESULT = "[Tool call did not finish: the run ended before this tool returned.]"


def _sits_after(messages: Sequence[AnyMessage], call_index: int, result: ToolMessage) -> bool:
    """Tell whether result is already in the run of tool messages right after its call."""
    for follower in messages[call_index + 1 :]:
        if not isinstance(follower, ToolMessage):
            return False
        if follower is result:
            return True
    return False


def provider_transcript(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Return messages with each tool call's result moved beside it.

    A misplaced real result is moved into its slot, a call with no result is answered as
    unfinished, and a result with no call (or a second result for one call) is dropped.
    """
    results: dict[str, ToolMessage] = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            results.setdefault(message.tool_call_id, message)

    shaped: list[AnyMessage] = []
    moved = unfinished = 0
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            continue
        shaped.append(message)
        if not isinstance(message, AIMessage):
            continue
        # OpenAI is sent the unparsed calls as tool calls too, so they need a result as well.
        parsed: list[ToolCall] = message.tool_calls
        unparsed: list[InvalidToolCall] = message.invalid_tool_calls
        calls = [(c["id"], c["name"]) for c in parsed] + [(c["id"], c["name"]) for c in unparsed]
        for call_id, name in calls:
            if not call_id:
                continue
            result = results.get(call_id)
            if result is None:
                unfinished += 1
                result = ToolMessage(
                    content=UNFINISHED_TOOL_RESULT,
                    tool_call_id=call_id,
                    name=name,
                    status="error",
                )
            elif not _sits_after(messages, index, result):
                moved += 1
            shaped.append(result)

    dropped = len(messages) + unfinished - len(shaped)
    if moved or unfinished or dropped:
        log.warning(
            f"{LogTag.AGENT} Reshaped the tool results a thread held out of place",
            moved_tool_results=moved,
            unfinished_tool_calls=unfinished,
            dropped_tool_results=dropped,
        )
    return shaped


def provider_input(model_input: LanguageModelInput) -> LanguageModelInput:
    """Return a message-list input as provider_transcript shapes it; a prompt string or value has no tool use."""
    if isinstance(model_input, str) or not isinstance(model_input, Sequence):
        return model_input
    return provider_transcript(cast("list[AnyMessage]", convert_to_messages(model_input)))
