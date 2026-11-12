"""Where each message sits in the request the model receives.

Every provider's prompt cache reuses the longest prefix an earlier request
shared, and OpenAI only a whole earlier request. So each call must begin with
the previous call on its thread, byte for byte: the request is the thread,
append-only. Only LEADING_SLOTS — text that changes when the user edits a
setting, never per turn — are lifted to the front, latest copy only. Every
other message, the per-turn recall and clock included, is sent where the turn
wrote it and is never pruned or reordered (docs/llm-cache-measurements.md).
"""

from enum import IntEnum
from typing import TypedDict, TypeVar, cast

from langchain_core.messages import AnyMessage, BaseMessage

#: ``mark`` returns the message it was given, so it must preserve the concrete
#: type — a caller stamping a ``SystemMessage`` gets a ``SystemMessage`` back,
#: not the ``AnyMessage`` union, which would erase the type at every call site.
M = TypeVar("M", bound=BaseMessage)

#: Marker keys stamped onto ``additional_kwargs``. A message declares its slot;
#: it does not rely on where an emitter happened to put it.
DYNAMIC_CONTEXT_MARKER = "dynamic_context"
MEMORY_RECALL_MARKER = "memory_recall"
TIME_CONTEXT_MARKER = "time_context"
#: Written only by the retired onboarding prompt; replayed checkpoints still carry it.
ONBOARDING_MARKER = "onboarding_context"

#: Stamped on the surface-change note GAIA writes into the thread. The note
#: stays in the CONVERSATION slot (inline, never pruned) but is not the user's words.
PRESENCE_NOTE_MARKER = "presence_note"

#: Stamped on the note that GAIA already reacted to the user's message; inline like the presence note.
REACTION_NOTE_MARKER = "reaction_note"

#: Pre-split threads carried one combined dynamic message marked with both
#: ``dynamic_context`` and this. Checkpoints written then are still replayed, so
#: it must keep resolving to the stable dynamic slot.
LEGACY_DYNAMIC_MARKER = "memory_message"

#: The background-executor result is identified by ``name`` rather than a marker:
#: the comms narrator builds it with no graph-state context to stamp one.
BACKGROUND_EXECUTOR_NAME = "background_executor"

#: ``additional_kwargs["lc_source"]`` LangChain stamps on the summary it writes.
#: The summary rides the thread as a HumanMessage but is GAIA-authored.
SUMMARY_SOURCE = "summarization"


class MessageMetadata(TypedDict, total=False):
    """The additional_kwargs keys GAIA reads back off a checkpointed message."""

    lc_source: str


def is_conversation_summary(message: BaseMessage) -> bool:
    """Whether message is a summarization digest rather than something the user said."""
    metadata: MessageMetadata = cast("MessageMetadata", message.additional_kwargs)
    return metadata.get("lc_source") == SUMMARY_SOURCE


class PromptSlot(IntEnum):
    """What a message is. Declaration order is the order the leading slots are sent in."""

    STATIC = 0
    DYNAMIC_STABLE = 1
    ONBOARDING = 2
    MEMORY_RECALL = 3
    CONVERSATION = 4
    TIME = 5


#: Lifted to the front of every request, latest copy only, stale copies pruned
#: from the thread. They change only on a settings edit, which costs one cold call.
LEADING_SLOTS: frozenset[PromptSlot] = frozenset(
    {PromptSlot.STATIC, PromptSlot.DYNAMIC_STABLE, PromptSlot.ONBOARDING}
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


def is_gaia_authored_note(message: AnyMessage) -> bool:
    """Whether message is a note GAIA wrote into a turn rather than something the user said.

    The presence and reaction notes, the per-turn recall block and the clock: true for the turn
    that wrote them, so they stay inline with it and fold away with it, never
    restated as summary text that would read as current.
    """
    return (
        has_marker(message, PRESENCE_NOTE_MARKER)
        or has_marker(message, REACTION_NOTE_MARKER)
        or slot_of(message) in (PromptSlot.MEMORY_RECALL, PromptSlot.TIME)
    )


def mark(message: M, *names: str) -> M:
    """Stamp slot markers on message so its slot survives checkpointing."""
    for name in names:
        message.additional_kwargs[name] = True
    return message


#: A system message's slot by the first marker it carries, in this order.
_SLOT_BY_MARKER: tuple[tuple[str, PromptSlot], ...] = (
    (MEMORY_RECALL_MARKER, PromptSlot.MEMORY_RECALL),
    (ONBOARDING_MARKER, PromptSlot.ONBOARDING),
    (DYNAMIC_CONTEXT_MARKER, PromptSlot.DYNAMIC_STABLE),
    (LEGACY_DYNAMIC_MARKER, PromptSlot.DYNAMIC_STABLE),
)


def slot_of(message: AnyMessage) -> PromptSlot:
    """Which slot message belongs in.

    Check order is load-bearing: a block marked both volatile and dynamic is
    MEMORY_RECALL, and a background report older code wrote as a system message
    is conversation, never the static prompt.
    """
    if message.type != "system":
        return (
            PromptSlot.TIME if has_marker(message, TIME_CONTEXT_MARKER) else PromptSlot.CONVERSATION
        )
    if message.name == BACKGROUND_EXECUTOR_NAME:
        return PromptSlot.CONVERSATION
    return next(
        (slot for marker, slot in _SLOT_BY_MARKER if has_marker(message, marker)),
        PromptSlot.STATIC,
    )
