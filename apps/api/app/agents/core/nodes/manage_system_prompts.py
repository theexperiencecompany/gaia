"""Shape the message array into the request the lane's prompt cache can reuse.

Slot-ordered providers (Gemini, OpenRouter-wire): stacking timestamped
dynamic-context messages across turns shatters the implicit prompt-cache prefix,
so this node keeps one message per slot and emits them in the order
request_slot_order declares.

Append-only providers (OpenAI): a call is cached only when it begins with the
previous call whole, so only the leading slots are lifted and deduplicated;
every other message stays where it happened, and a hook's per-call frame is
committed to the thread when its text changes. The rationale lives with the
slot definitions, not here.

The bigtool override invokes the LLM with this hook's returned
state["messages"] directly, so the return value IS the request — but the
persistent checkpoint still grows unfiltered, so dropped ids ride back on
PRUNED_MESSAGE_IDS_KEY for the model node to tombstone. Runs as a pre-model
hook so it also fires on cancellation (end-of-graph hooks do not).
"""

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import time
from typing import cast
from uuid import uuid4

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import (
    LEADING_SLOTS,
    PER_CALL_SLOTS,
    SINGLETON_SLOTS,
    TAIL_VOLATILE_PROVIDERS,
    PromptSlot,
    is_append_only,
    request_slot_order,
    slot_of,
)
from app.agents.llm.lane import ModelLane
from app.constants.log_tags import LogTag
from app.models.agent_models import config_agent_name, read_agent_configurable
from app.override.langgraph_bigtool.utils import (
    INJECTED_MESSAGES_KEY,
    PRUNED_MESSAGE_IDS_KEY,
    State,
)
from app.services.latency_metrics import observe_graph_node
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

#: Wide-event field per slot. Spelled out rather than derived from the enum
#: names so renaming a slot cannot silently rename a field that dashboards and
#: saved queries already read.
_KEPT_FIELDS = {
    PromptSlot.STATIC: "kept_static",
    PromptSlot.DYNAMIC_STABLE: "kept_dynamic",
    PromptSlot.ONBOARDING: "kept_onboarding",
    PromptSlot.TODO_CONTEXT: "kept_todo",
    PromptSlot.BACKGROUND_EXECUTOR: "kept_bg_exec",
    PromptSlot.EXECUTOR_STATUS: "kept_exec_status",
    PromptSlot.BROWSER_TASK: "kept_browser_task",
    PromptSlot.MEMORY_RECALL: "kept_memory_recall",
    PromptSlot.TIME: "kept_time",
}


def manage_system_prompts_node(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Keep the latest message per slot and emit them in canonical slot order (timed)."""
    start = time.perf_counter()
    try:
        return _manage_system_prompts(state, config)
    finally:
        observe_graph_node(
            time.perf_counter() - start,
            node="manage_system_prompts",
            agent=config_agent_name(config),
        )


@dataclass(frozen=True)
class _KeptPrompts:
    """One pass over the slots: what is sent, and what it pruned."""

    messages: list[AnyMessage]
    by_slot: dict[PromptSlot, list[AnyMessage]]
    pruned_ids: list[str]
    dropped_system: int
    dropped_time: int
    #: Per-call frames this request introduces, which the model node must commit.
    committed_frames: list[AnyMessage] = field(default_factory=list)


def _keep_latest_per_slot(
    by_slot: dict[PromptSlot, list[AnyMessage]], slot_order: tuple[PromptSlot, ...]
) -> _KeptPrompts:
    """Emit slots in order, keeping only the latest message of a singleton slot."""
    messages: list[AnyMessage] = []
    kept_by_slot: dict[PromptSlot, list[AnyMessage]] = {}
    pruned_ids: list[str] = []
    dropped_system = 0
    dropped_time = 0
    for slot in slot_order:
        group = by_slot.get(slot)
        if not group:
            continue
        if slot not in SINGLETON_SLOTS:
            messages.extend(group)
            kept_by_slot[slot] = group
            continue
        messages.append(group[-1])
        kept_by_slot[slot] = [group[-1]]
        for stale in group[:-1]:
            if slot is PromptSlot.TIME:
                dropped_time += 1
            else:
                dropped_system += 1
            if stale.id:
                pruned_ids.append(stale.id)
    return _KeptPrompts(messages, kept_by_slot, pruned_ids, dropped_system, dropped_time)


def _append_only_request(messages: list[AnyMessage]) -> _KeptPrompts:
    """Lift the latest leading slots, then replay the thread in order, committing changed frames.

    A per-call frame with an id was committed by an earlier call and stays where it
    was. A fresh one (no id: it never passed the reducer) is dropped when it repeats
    the slot's last committed text, else it is sent here and committed so the next
    call carries it at the same position.
    """
    by_slot: defaultdict[PromptSlot, list[AnyMessage]] = defaultdict(list)
    for message in messages:
        by_slot[slot_of(message)].append(message)

    leading: list[AnyMessage] = []
    pruned_ids: list[str] = []
    dropped_system = 0
    for slot in PromptSlot:
        group = by_slot.get(slot)
        if slot not in LEADING_SLOTS or not group:
            continue
        *stale, latest = group
        leading.append(latest)
        pruned_ids.extend(m.id for m in stale if m.id)
        dropped_system += len(stale)

    thread_order: list[AnyMessage] = []
    committed: list[AnyMessage] = []
    last_frame_text: dict[PromptSlot, str] = {}
    for message in messages:
        slot = slot_of(message)
        if slot in LEADING_SLOTS:
            continue
        if slot in PER_CALL_SLOTS:
            text = extract_text_content(message.content)
            if message.id is None:
                if last_frame_text.get(slot) == text:
                    continue
                message = message.model_copy(update={"id": str(uuid4())})
                committed.append(message)
            last_frame_text[slot] = text
        thread_order.append(message)

    request = [*leading, *thread_order]
    kept_by_slot: defaultdict[PromptSlot, list[AnyMessage]] = defaultdict(list)
    for message in request:
        kept_by_slot[slot_of(message)].append(message)
    return _KeptPrompts(request, dict(kept_by_slot), pruned_ids, dropped_system, 0, committed)


def _staged_commits(state: State, kept: _KeptPrompts) -> list[AnyMessage]:
    """Merge the frames to commit with what earlier hooks staged, in request order.

    The thread must hold them in the order the request sent them, or the next
    call would not begin with this one.
    """
    staged = cast(
        "list[AnyMessage]", cast("dict[str, object]", state).get(INJECTED_MESSAGES_KEY) or []
    )
    if not kept.committed_frames:
        return staged
    to_commit = {id(m) for m in (*staged, *kept.committed_frames)}
    return [m for m in kept.messages if id(m) in to_commit]


def _manage_system_prompts(state: State, config: RunnableConfig) -> State:
    """Keep the latest message per slot and emit them in canonical slot order.

    The order depends on the provider of the run's lane — see request_slot_order.
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state

        by_slot: defaultdict[PromptSlot, list[AnyMessage]] = defaultdict(list)
        for message in messages:
            by_slot[slot_of(message)].append(message)

        lane = ModelLane.from_configurable(read_agent_configurable(config).lane)
        provider = lane.provider if lane else None
        append_only = is_append_only(provider)
        if append_only:
            slot_order = tuple(PromptSlot)
            kept = _append_only_request(messages)
        else:
            slot_order = request_slot_order(provider)
            kept = _keep_latest_per_slot(by_slot, slot_order)

        # A short content fingerprint per slot, to name which slot moved the
        # BYTE cache prefix. Hashes, never content. Built from ``kept.by_slot``
        # since a singleton slot sends only its LAST message.
        slot_text = {
            slot.name.lower(): "\x00".join(
                extract_text_content(m.content) for m in kept.by_slot[slot]
            )
            for slot in slot_order
            if slot in kept.by_slot
        }
        slot_digests = {
            name: hashlib.blake2b(text.encode(), digest_size=4).hexdigest()
            for name, text in slot_text.items()
        }
        # Sizes answer what the digests cannot: which slot owns the bytes
        # behind the cache boundary. Characters, not tokens — no tokenizer
        # here, and ~4 chars/token is close enough to rank the slots.
        slot_chars = {name: len(text) for name, text in slot_text.items()}
        # OpenRouter-wire providers place memory recall after the conversation,
        # Gemini ahead of it, and OpenAI inline where each turn wrote it.

        log.set(
            prompt_pruning={
                "slot_digests": slot_digests,
                "slot_chars": slot_chars,
                "messages_in": len(messages),
                "messages_out": len(kept.messages),
                "dropped_system_prompts": kept.dropped_system,
                "dropped_time_context": kept.dropped_time,
                **{field: bool(by_slot.get(slot)) for slot, field in _KEPT_FIELDS.items()},
                "tail_layout": provider in TAIL_VOLATILE_PROVIDERS,
                "append_only": append_only,
                "committed_frames": len(kept.committed_frames),
            }
        )

        return cast(
            State,
            {
                **state,
                "messages": kept.messages,
                PRUNED_MESSAGE_IDS_KEY: kept.pruned_ids,
                INJECTED_MESSAGES_KEY: _staged_commits(state, kept),
            },
        )

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in manage system prompts node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
