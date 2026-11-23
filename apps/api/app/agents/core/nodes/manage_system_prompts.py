"""Shape the thread into an append-only request: leading slots first, the rest as written.

Each call must begin with the previous call on its thread, byte for byte, or the
provider's prompt cache re-bills the history (see app.agents.context.slots). The
leading slots are re-emitted by every turn, so only their latest copy is sent and
the stale ones are pruned; every other message is sent in thread order.

The bigtool override invokes the LLM with this hook's returned
state["messages"] directly, so the return value IS the request — but the
persistent checkpoint still grows unfiltered, so dropped ids ride back on
PRUNED_MESSAGE_IDS_KEY for the model node to tombstone. Runs as a pre-model
hook so it also fires on cancellation (end-of-graph hooks do not).
"""

from dataclasses import dataclass
import hashlib
import time
from typing import cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import LEADING_SLOTS, PromptSlot, slot_of
from app.constants.log_tags import LogTag
from app.models.agent_models import config_agent_name
from app.override.langgraph_bigtool.utils import PRUNED_MESSAGE_IDS_KEY, State
from app.services.latency_metrics import observe_graph_node
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

#: Wide-event field per leading slot. Spelled out rather than derived from the enum
#: names so renaming a slot cannot silently rename a field that dashboards and
#: saved queries already read.
_KEPT_FIELDS = {
    PromptSlot.STATIC: "kept_static",
    PromptSlot.DYNAMIC_STABLE: "kept_dynamic",
    PromptSlot.ONBOARDING: "kept_onboarding",
}


def manage_system_prompts_node(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Lift the latest leading slots ahead of the thread, which is sent as written (timed)."""
    start = time.perf_counter()
    try:
        return _manage_system_prompts(state)
    finally:
        observe_graph_node(
            time.perf_counter() - start,
            node="manage_system_prompts",
            agent=config_agent_name(config),
        )


@dataclass(frozen=True)
class AppendOnlyRequest:
    """The request built from a thread, and the stale leading copies it dropped."""

    messages: list[AnyMessage]
    leading: dict[PromptSlot, AnyMessage]
    #: Ids of the dropped copies the checkpoint holds, for the model node to tombstone.
    pruned_ids: list[str]
    dropped: int


def build_request(thread: list[AnyMessage]) -> AppendOnlyRequest:
    """Return the latest copy of each leading slot, in declaration order, then the rest of thread in order."""
    latest: dict[PromptSlot, AnyMessage] = {}
    stale: list[AnyMessage] = []
    rest: list[AnyMessage] = []
    for message in thread:
        slot = slot_of(message)
        if slot not in LEADING_SLOTS:
            rest.append(message)
            continue
        if slot in latest:
            stale.append(latest[slot])
        latest[slot] = message
    leading = {slot: latest[slot] for slot in PromptSlot if slot in latest}
    pruned_ids = [m.id for m in stale if m.id]
    return AppendOnlyRequest([*leading.values(), *rest], leading, pruned_ids, len(stale))


def _digest(text: str) -> str:
    """Return a fixed-width fingerprint of text, so a log carries which slot moved but never its content."""
    return hashlib.blake2b(text.encode(), digest_size=4).hexdigest()


def _manage_system_prompts(state: State) -> State:
    """Build the append-only request and record which leading slot could have moved the prefix."""
    try:
        thread = state.get("messages", [])
        if not thread:
            return state

        request = build_request(thread)
        # A changed leading slot is the one thing that can still move the cache
        # boundary, so each gets a fingerprint and a size. Hashes, never content;
        # characters, not tokens (~4 chars/token is close enough to rank them).
        leading_text = {
            slot.name.lower(): extract_text_content(message.content)
            for slot, message in request.leading.items()
        }
        log.set(
            prompt_pruning={
                "slot_digests": {name: _digest(text) for name, text in leading_text.items()},
                "slot_chars": {name: len(text) for name, text in leading_text.items()},
                "messages_in": len(thread),
                "messages_out": len(request.messages),
                "dropped_system_prompts": request.dropped,
                **{field: slot in request.leading for slot, field in _KEPT_FIELDS.items()},
            }
        )
        return cast(
            State,
            {**state, "messages": request.messages, PRUNED_MESSAGE_IDS_KEY: request.pruned_ids},
        )

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in manage system prompts node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
