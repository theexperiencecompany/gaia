"""Stop a repeated cumulative usage frame from being billed once per stream chunk.

Some providers (DEV_LLM's deepseek-v4-flash) repeat the OpenAI-wire cumulative
usage snapshot on nearly every chunk instead of once (openrouter.ai's
behavior) — an 8-chunk answer saw 5 frames of prompt_tokens=89 with completion
counts 1 → 6 → 10 → 10 → 10. AIMessageChunk.__add__ ADDS usage via add_usage,
so the merged message claimed 445/37 tokens for a call that spent 89/10,
corrupting billing, budget checks, and the frontend's usage display.

Fix: convert each snapshot to the delta since the last one before it leaves
the stream — summing deltas lands on the real final snapshot, and
single-frame providers are unaffected. Not fixed in add_usage itself: that
function also totals usage ACROSS calls for UsageMetadataCallbackHandler,
which must keep adding. run_manager stays in the signature but langchain-core
1.4.8 never passes it (verified zero calls across all 4 entry points).
"""

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from typing import Any, cast

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from langchain_openrouter import ChatOpenRouter

from shared.py.wide_events import log

#: Typed as pass-throughs: hands them whatever it was handed. Spelling the
#: params out would make mypy map object-typed **kwargs onto the run_manager
#: slot these calls deliberately leave empty.
_ORIGINAL_STREAM: Callable[..., Iterator[ChatGenerationChunk]] = ChatOpenRouter._stream
_ORIGINAL_ASTREAM: Callable[..., AsyncIterator[ChatGenerationChunk]] = ChatOpenRouter._astream


def _delta(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Subtract one usage snapshot from the next, recursing into the detail dicts.

    Keys are taken from the union of both sides so a counter that appears
    mid-stream, or stops being reported, still nets out to the latest snapshot
    when the deltas are summed.
    """
    delta: dict[str, Any] = {}
    for key in current.keys() | previous.keys():
        current_value = current.get(key)
        previous_value = previous.get(key)
        if isinstance(current_value, Mapping) or isinstance(previous_value, Mapping):
            delta[key] = _delta(
                previous_value if isinstance(previous_value, Mapping) else {},
                current_value if isinstance(current_value, Mapping) else {},
            )
        else:
            delta[key] = int(current_value or 0) - int(previous_value or 0)
    return delta


def _normalise(
    chunk: ChatGenerationChunk, previous: Mapping[str, Any]
) -> tuple[ChatGenerationChunk, Mapping[str, Any]]:
    """Replace a chunk's cumulative usage with the delta since previous.

    previous is the last snapshot seen, empty before the first one — an
    empty mapping subtracts to itself, so the first frame's delta is the frame.
    Returns the chunk to emit and the snapshot to subtract from next time.
    Chunks carrying no usage pass through untouched.
    """
    message = chunk.message
    # Only an AI message can carry usage, and every AIMessageChunk defines the
    # field (defaulting to None) — so this narrows rather than probing.
    usage = message.usage_metadata if isinstance(message, AIMessage) else None
    if not usage:
        return chunk, previous

    delta = cast(UsageMetadata, _delta(previous, usage))
    normalised = ChatGenerationChunk(
        message=message.model_copy(update={"usage_metadata": delta}),
        generation_info=chunk.generation_info,
    )
    return normalised, usage


def _warn_if_langchain_starts_passing_a_run_manager(run_manager: object) -> None:
    """Warn if langchain ever passes these wrappers a real run_manager.

    It doesn't today: langchain-core 1.4.8 calls _stream/_astream as (messages, stop=stop,
    **kwargs) from all four sites (stream, astream, _generate_with_cache,
    _agenerate_with_cache). If it ever did, the streamed and billed usage numbers would
    silently diverge unless this wrapper forwarded it — hence log.warning, not a comment.
    """
    if run_manager is not None:
        log.warning(
            "openrouter usage patch received a run_manager it does not forward",
            run_manager_type=type(run_manager).__name__,
        )


def _stream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    run_manager: CallbackManagerForLLMRun | None = None,
    **kwargs: object,
) -> Iterator[ChatGenerationChunk]:
    """ChatOpenRouter._stream with cumulative usage snapshots turned into deltas."""
    _warn_if_langchain_starts_passing_a_run_manager(run_manager)
    previous: Mapping[str, Any] = {}
    for chunk in _ORIGINAL_STREAM(self, messages, stop=stop, **kwargs):
        normalised, previous = _normalise(chunk, previous)
        yield normalised


async def _astream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    run_manager: AsyncCallbackManagerForLLMRun | None = None,
    **kwargs: object,
) -> AsyncIterator[ChatGenerationChunk]:
    """ChatOpenRouter._astream with cumulative usage snapshots turned into deltas."""
    _warn_if_langchain_starts_passing_a_run_manager(run_manager)
    previous: Mapping[str, Any] = {}
    async for chunk in _ORIGINAL_ASTREAM(self, messages, stop=stop, **kwargs):
        normalised, previous = _normalise(chunk, previous)
        yield normalised


def apply() -> None:
    """Rebind ChatOpenRouter's streaming generators to the usage-normalising ones."""
    # setattr through a variable name: monkeypatching a method is exactly what
    # this patch exists to do, and neither mypy's method-assign check nor ruff's
    # B010 has a way to express "this assignment is the point".
    replacements: dict[str, object] = {"_stream": _stream, "_astream": _astream}
    for method_name, replacement in replacements.items():
        setattr(ChatOpenRouter, method_name, replacement)


apply()
