"""Stop a repeated cumulative ``usage`` frame from being billed once per stream chunk.

On the OpenAI wire, ``stream_options: {include_usage: true}`` asks for token
counts as a *cumulative snapshot of the whole response*. Nothing in the protocol
says the snapshot arrives once, and providers differ: openrouter.ai sends it on
a single terminal chunk, while the DEV_LLM lane (a deepseek-v4-flash endpoint)
repeats it on nearly every chunk — a live 8-chunk answer carried five frames,
each reporting ``prompt_tokens: 89`` with a completion count climbing
1 → 6 → 10 → 10 → 10.

``ChatOpenRouter._stream``/``_astream`` attach every one of those snapshots to
its chunk as ``usage_metadata``, and ``AIMessageChunk.__add__``
(``langchain_core.messages.ai``) merges chunks with ``add_usage``, which ADDS.
So the merged message claimed 445 input and 37 output tokens for a call that
really spent 89 and 10 — the inflation factor being however many chunks the
answer arrived in. Everything downstream reads that merged message:
``extract_message_usage`` → ``record_llm_call`` (the daily USD budget and the
per-request token ceiling), the ``model.*`` wide event, and the per-turn usage
``UsageMetadataCallbackHandler`` hands the frontend.

The fix is at the source: convert each snapshot into the delta since the last
one before it leaves the stream. Summing deltas lands exactly on the final
snapshot, so every additive consumer — the chunk merge, the callback handler,
the tracers — arrives at the number the provider actually reported, and the
single-frame providers are unaffected (their one frame's delta is itself).
Deliberately NOT fixed in ``add_usage``: the same function is what
``UsageMetadataCallbackHandler`` uses to total usage *across* calls, which must
keep adding.

Normalising the chunk is the whole fix: ``BaseChatModel`` fires
``on_llm_new_token`` itself, with the chunk this wrapper just yielded, so the
streamed view and the merged message agree without the wrapper touching
callbacks. ``run_manager`` stays in the signature because it is part of the
method langchain declares, but langchain-core 1.4.8 never passes it — all four
call sites (``stream``, ``astream``, ``_generate_with_cache``,
``_agenerate_with_cache``) invoke ``_stream``/``_astream`` as
``(messages, stop=stop, **kwargs)``. An earlier version of this patch fired the
callback itself under ``if run_manager:``; that branch was verified to execute
zero times across all four entry points and has been removed.
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

#: The generators being wrapped, typed as the pass-throughs this module treats
#: them as: it hands them whatever it was handed. Spelling the parameters out
#: instead would make mypy map an ``object``-typed ``**kwargs`` onto the
#: concrete ``run_manager`` slot these calls deliberately leave empty.
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
    """Replace a chunk's cumulative usage with the delta since ``previous``.

    ``previous`` is the last snapshot seen, empty before the first one — an
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
    """Loud if langchain ever hands these wrappers a run_manager of their own.

    It does not today: langchain-core 1.4.8 invokes ``_stream``/``_astream`` as
    ``(messages, stop=stop, **kwargs)`` from all four call sites (``stream``,
    ``astream``, ``_generate_with_cache``, ``_agenerate_with_cache``) and fires
    ``on_llm_new_token`` itself with the chunk yielded here — which is why
    normalising the chunk is the entire fix.

    If a future version starts passing one, this wrapper would have to forward
    it (or fire the callback itself), because upstream would otherwise report
    the raw cumulative snapshot while the merged message reports the delta. A
    silent divergence between the streamed numbers and the billed ones is the
    exact failure this patch exists to prevent, so it is a warning, not a
    comment: ``log.warning`` puts it on the wide event's ``warnings[]``.
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
    """``ChatOpenRouter._stream`` with cumulative usage snapshots turned into deltas."""
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
    """``ChatOpenRouter._astream`` with cumulative usage snapshots turned into deltas."""
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
