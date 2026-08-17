"""Collapse the message array to one message per prompt slot, in canonical order.

Stacking ten timestamped dynamic-context messages across a ten-turn conversation
is what shatters the LLM's implicit prompt-cache prefix. This node discards every
older copy of each slot and rebuilds the array in the order declared by
:class:`~app.agents.context.slots.PromptSlot`, so the model sees the same shape
on every turn.

The ordering rationale lives with the enum, not here — this node only applies it.

The bigtool override's ``acall_model`` calls hooks via
``state = await execute_hooks(...)`` and then invokes the LLM with
``state["messages"]`` directly, so this return value IS the request. The
persistent checkpoint still grows unfiltered (LangGraph's ``add_messages``
reducer never reorders by id), which is why the dropped ids ride back on
``PRUNED_MESSAGE_IDS_KEY`` for the model node to tombstone.

Runs as a pre-model hook so it also fires when a generation is cancelled
(end-of-graph hooks do not run on cancellation).
"""

from collections import defaultdict
from typing import cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import SINGLETON_SLOTS, PromptSlot, slot_of
from app.constants.log_tags import LogTag
from app.override.langgraph_bigtool.utils import PRUNED_MESSAGE_IDS_KEY, State
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


def manage_system_prompts_node(state: State, config: RunnableConfig, store: BaseStore) -> State:
    """Keep the latest message per slot and emit them in canonical slot order."""
    try:
        messages = state.get("messages", [])
        if not messages:
            return state

        by_slot: defaultdict[PromptSlot, list[AnyMessage]] = defaultdict(list)
        for message in messages:
            by_slot[slot_of(message)].append(message)

        kept: list[AnyMessage] = []
        pruned_ids: list[str] = []
        dropped_system = 0
        dropped_time = 0
        for slot in PromptSlot:
            group = by_slot.get(slot)
            if not group:
                continue
            if slot not in SINGLETON_SLOTS:
                kept.extend(group)
                continue
            kept.append(group[-1])
            for stale in group[:-1]:
                if slot is PromptSlot.TIME:
                    dropped_time += 1
                else:
                    dropped_system += 1
                if stale.id:
                    pruned_ids.append(stale.id)

        log.set(
            prompt_pruning={
                "messages_in": len(messages),
                "messages_out": len(kept),
                "dropped_system_prompts": dropped_system,
                "dropped_time_context": dropped_time,
                **{field: bool(by_slot.get(slot)) for slot, field in _KEPT_FIELDS.items()},
            }
        )

        return cast(State, {**state, "messages": kept, PRUNED_MESSAGE_IDS_KEY: pruned_ids})

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in manage system prompts node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
