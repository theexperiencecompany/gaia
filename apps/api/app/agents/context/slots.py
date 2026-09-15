"""Where each message sits in the request the model receives.

The order below is the whole cache contract in one place, replacing an
emergent hand-rolled scan nothing else could see. Two constraints fix it:

* langchain-google-genai promotes a SystemMessage to system_instruction only
  while the system block is leading and CONTIGUOUS — the first non-system
  message ends it and every later SystemMessage is silently dropped.
* Implicit prompt caching matches on longest common prefix, so byte-stable
  slots sort ahead of per-turn churn, with the clock last so it never moves
  the boundary.

The first constraint is Gemini's alone; OpenAI-wire providers accept a
system message anywhere, so request_slot_order moves their per-turn slots
BEHIND the conversation for a strictly better cache layout.
"""

from enum import IntEnum
from typing import TypeVar

from langchain_core.messages import AnyMessage, BaseMessage

from app.agents.llm.types import LLMProviderName

#: ``mark`` returns the message it was given, so it must preserve the concrete
#: type — a caller stamping a ``SystemMessage`` gets a ``SystemMessage`` back,
#: not the ``AnyMessage`` union, which would erase the type at every call site.
M = TypeVar("M", bound=BaseMessage)

#: Marker keys stamped onto ``additional_kwargs``. A message declares its slot;
#: it does not rely on where an emitter happened to put it.
DYNAMIC_CONTEXT_MARKER = "dynamic_context"
MEMORY_RECALL_MARKER = "memory_recall"
TODO_CONTEXT_MARKER = "todo_context"
EXECUTOR_STATUS_MARKER = "executor_status"
TIME_CONTEXT_MARKER = "time_context"
ONBOARDING_MARKER = "onboarding_context"

#: Pre-split threads carried one combined dynamic message marked with both
#: ``dynamic_context`` and this. Checkpoints written then are still replayed, so
#: it must keep resolving to the stable dynamic slot.
LEGACY_DYNAMIC_MARKER = "memory_message"

#: The background-executor result is identified by ``name`` rather than a marker:
#: the comms narrator builds it with no graph-state context to stamp one.
BACKGROUND_EXECUTOR_NAME = "background_executor"


class PromptSlot(IntEnum):
    """Canonical position of a message. Declaration order IS request order."""

    STATIC = 0
    DYNAMIC_STABLE = 1
    ONBOARDING = 2
    TODO_CONTEXT = 3
    BACKGROUND_EXECUTOR = 4
    EXECUTOR_STATUS = 5
    MEMORY_RECALL = 6
    CONVERSATION = 7
    TIME = 8


#: Slots holding exactly one message, so a long thread doesn't stack copies
#: and shatter the cache prefix. ``CONVERSATION`` is the only accumulator.
SINGLETON_SLOTS = frozenset(slot for slot in PromptSlot if slot is not PromptSlot.CONVERSATION)

#: Slots whose text changes every request. Where allowed they sort behind the
#: conversation (:func:`request_slot_order`); ahead of it they'd move the
#: cache boundary every turn and re-send the whole history uncached.
TAIL_VOLATILE_SLOTS: frozenset[PromptSlot] = frozenset(
    {
        PromptSlot.TODO_CONTEXT,
        PromptSlot.BACKGROUND_EXECUTOR,
        PromptSlot.EXECUTOR_STATUS,
        PromptSlot.MEMORY_RECALL,
    }
)

#: Providers on the OpenAI wire format, which apply a system message wherever
#: it appears. Gemini stays off this list for caching, not content loss:
#: moving volatile slots back would fold per-turn bytes INTO its cached block.
TAIL_VOLATILE_PROVIDERS: frozenset[LLMProviderName] = frozenset(
    {LLMProviderName.OPENROUTER, LLMProviderName.CUSTOM}
)


def request_slot_order(provider: str | None) -> tuple[PromptSlot, ...]:
    """Return the slot order a request bound for provider is emitted in.

    Gemini gets the declaration order (cache covers only [static,
    dynamic_stable]); OpenAI-wire providers move per-turn slots after the
    conversation so it joins the cached prefix (measured: 35.2% -> 94.9%
    isolated, ~45% -> 80-85% steady-state; see docs/llm-cache-measurements.md).
    """
    if provider not in TAIL_VOLATILE_PROVIDERS:
        return tuple(PromptSlot)
    return (
        *(
            slot
            for slot in PromptSlot
            if slot < PromptSlot.CONVERSATION and slot not in TAIL_VOLATILE_SLOTS
        ),
        PromptSlot.CONVERSATION,
        *(slot for slot in PromptSlot if slot in TAIL_VOLATILE_SLOTS),
        *(slot for slot in PromptSlot if slot > PromptSlot.CONVERSATION),
    )


def has_marker(message: AnyMessage, name: str) -> bool:
    """Whether message carries marker name.

    Checks additional_kwargs (where LangChain persists custom kwargs) and
    falls back to model_extra, because a marker passed as a bare constructor
    kwarg lands there — and checkpoints written before the markers moved still
    replay through here.
    """
    if message.additional_kwargs.get(name):
        return True
    model_extra = getattr(message, "model_extra", None)
    return bool(isinstance(model_extra, dict) and model_extra.get(name))


def mark(message: M, *names: str) -> M:
    """Stamp slot markers on message so its slot survives checkpointing."""
    for name in names:
        message.additional_kwargs[name] = True
    return message


def slot_of(message: AnyMessage) -> PromptSlot:
    """Which slot message belongs in.

    Order of the checks is load-bearing where markers overlap: the legacy
    combined message carries dynamic_context *and* memory_message, and a
    volatile block must be read as MEMORY_RECALL even if a future emitter
    also stamps it dynamic.
    """
    if message.type != "system":
        return (
            PromptSlot.TIME if has_marker(message, TIME_CONTEXT_MARKER) else PromptSlot.CONVERSATION
        )
    if message.name == BACKGROUND_EXECUTOR_NAME:
        return PromptSlot.BACKGROUND_EXECUTOR
    if has_marker(message, EXECUTOR_STATUS_MARKER):
        return PromptSlot.EXECUTOR_STATUS
    if has_marker(message, MEMORY_RECALL_MARKER):
        return PromptSlot.MEMORY_RECALL
    if has_marker(message, TODO_CONTEXT_MARKER):
        return PromptSlot.TODO_CONTEXT
    if has_marker(message, ONBOARDING_MARKER):
        return PromptSlot.ONBOARDING
    if has_marker(message, DYNAMIC_CONTEXT_MARKER) or has_marker(message, LEGACY_DYNAMIC_MARKER):
        return PromptSlot.DYNAMIC_STABLE
    return PromptSlot.STATIC
