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

The wrapper drives the upstream generator with ``run_manager=None`` and fires
``on_llm_new_token`` itself, so streamed chunks and the merged message carry the
same normalised numbers rather than disagreeing. ``run_manager`` is used for
nothing else in either upstream generator (langchain-openrouter 0.2.3).
"""

from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any, cast

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from langchain_openrouter import ChatOpenRouter

_ORIGINAL_STREAM = ChatOpenRouter._stream
_ORIGINAL_ASTREAM = ChatOpenRouter._astream


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
    chunk: ChatGenerationChunk, previous: UsageMetadata | None
) -> tuple[ChatGenerationChunk, UsageMetadata | None]:
    """Replace a chunk's cumulative usage with the delta since ``previous``.

    Returns the chunk to emit and the snapshot to subtract from next time.
    Chunks carrying no usage pass through untouched.
    """
    message = chunk.message
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return chunk, previous

    delta = cast(UsageMetadata, _delta(previous or {}, usage))
    normalised = ChatGenerationChunk(
        message=message.model_copy(update={"usage_metadata": delta}),
        generation_info=chunk.generation_info,
    )
    return normalised, usage


def _token_callback_kwargs(chunk: ChatGenerationChunk) -> dict[str, Any]:
    """The ``on_llm_new_token`` keyword arguments upstream would have passed."""
    logprobs = (chunk.generation_info or {}).get("logprobs")
    return {"logprobs": logprobs} if logprobs else {}


def _stream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    run_manager: CallbackManagerForLLMRun | None = None,
    **kwargs: object,
) -> Iterator[ChatGenerationChunk]:
    """``ChatOpenRouter._stream`` with cumulative usage snapshots turned into deltas."""
    previous: UsageMetadata | None = None
    for chunk in _ORIGINAL_STREAM(self, messages, stop=stop, run_manager=None, **kwargs):
        normalised, previous = _normalise(chunk, previous)
        if run_manager:
            run_manager.on_llm_new_token(
                token=normalised.text, chunk=normalised, **_token_callback_kwargs(normalised)
            )
        yield normalised


async def _astream(
    self: ChatOpenRouter,
    messages: list[BaseMessage],
    stop: list[str] | None = None,
    run_manager: AsyncCallbackManagerForLLMRun | None = None,
    **kwargs: object,
) -> AsyncIterator[ChatGenerationChunk]:
    """``ChatOpenRouter._astream`` with cumulative usage snapshots turned into deltas."""
    previous: UsageMetadata | None = None
    async for chunk in _ORIGINAL_ASTREAM(self, messages, stop=stop, run_manager=None, **kwargs):
        normalised, previous = _normalise(chunk, previous)
        if run_manager:
            await run_manager.on_llm_new_token(
                token=normalised.text, chunk=normalised, **_token_callback_kwargs(normalised)
            )
        yield normalised


def apply() -> None:
    """Rebind ChatOpenRouter's streaming generators to the usage-normalising ones."""
    ChatOpenRouter._stream = _stream  # type: ignore[method-assign]
    ChatOpenRouter._astream = _astream  # type: ignore[method-assign]


apply()
