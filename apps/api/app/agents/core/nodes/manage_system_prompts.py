"""Collapse the message array to one message per prompt slot, in canonical order.

Stacking timestamped dynamic-context messages across turns is what shatters
the LLM's implicit prompt-cache prefix. This node discards every older copy
of each slot and rebuilds the array in the order declared by
:class:~app.agents.context.slots.PromptSlot, so the model sees the same
shape every turn. The ordering rationale lives with the enum, not here.

The bigtool override invokes the LLM with this hook's returned
state["messages"] directly, so the return value IS the request — but the
persistent checkpoint still grows unfiltered, so dropped ids ride back on
PRUNED_MESSAGE_IDS_KEY for the model node to tombstone. Runs as a pre-model
hook so it also fires on cancellation (end-of-graph hooks do not).
"""

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import time
from typing import cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import (
    SINGLETON_SLOTS,
    PromptSlot,
    request_slot_order,
    slot_of,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable, config_agent_name
from app.override.langgraph_bigtool.utils import PRUNED_MESSAGE_IDS_KEY, State
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


def _manage_system_prompts(state: State, config: RunnableConfig) -> State:
    """Keep the latest message per slot and emit them in canonical slot order.

    The order depends on the provider the request is bound for — see
    request_slot_order. The lane's provider is read off the configurable,
    which build_agent_config derives from the resolved ModelLane.
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state

        by_slot: defaultdict[PromptSlot, list[AnyMessage]] = defaultdict(list)
        for message in messages:
            by_slot[slot_of(message)].append(message)

        slot_order = request_slot_order(agent_configurable(config).get("provider"))
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

        log.set(
            prompt_pruning={
                "slot_digests": slot_digests,
                "slot_chars": slot_chars,
                "messages_in": len(messages),
                "messages_out": len(kept.messages),
                "dropped_system_prompts": kept.dropped_system,
                "dropped_time_context": kept.dropped_time,
                **{field: bool(by_slot.get(slot)) for slot, field in _KEPT_FIELDS.items()},
                # Which of the two layouts the request got. The tail layout is
                # what lets the conversation join the cached prefix, so a
                # sudden drop in cache hit rate is answered by this field.
                "tail_layout": slot_order != tuple(PromptSlot),
            }
        )

        return cast(
            State, {**state, "messages": kept.messages, PRUNED_MESSAGE_IDS_KEY: kept.pruned_ids}
        )

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in manage system prompts node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
