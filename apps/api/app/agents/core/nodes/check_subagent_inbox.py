"""Pre-model hook that drains the executor inbox at each turn boundary.

Runs before every executor LLM invocation. If subagents have pushed
progress updates via message_executor, they are injected into the
executor's state so the LLM can process them and optionally call
message_comms to forward to the user.

Only drains subagent_update messages. subagent_result messages are
left in the queue for wait_for_subagents() to collect — this prevents
the hook from consuming results that wait_for_subagents expects to see.

This is the GAIA equivalent of Claude Code's turn-boundary inbox check.
"""

import asyncio
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.core.background.inbox import get_executor_inbox
from shared.py.wide_events import log


async def check_subagent_inbox(
    state: Any,
    config: RunnableConfig,
    store: BaseStore,
) -> Any:
    """Drain subagent_update messages from executor inbox into state."""
    configurable = config.get("configurable", {})
    stream_id = configurable.get("stream_id")

    if not stream_id:
        return state

    queue = get_executor_inbox(stream_id)
    if not queue:
        return state

    # Non-blocking drain: consume only subagent_update messages.
    # Defer subagent_result so wait_for_subagents() can collect them.
    updates: list[str] = []
    deferred: list[Any] = []

    while True:
        try:
            item = queue.get_nowait()
            msg_type = item.get("type", "subagent_update")
            message = item.get("message", "")
            if msg_type == "subagent_result":
                deferred.append(item)
            elif msg_type == "comms_message":
                updates.append(f"[MESSAGE FROM COMMS]:\n{message}")
            else:
                agent = item.get("agent", "subagent")
                updates.append(f"[SUBAGENT_UPDATE from {agent}]\n{message}")
        except asyncio.QueueEmpty:
            break

    # Put result items back so wait_for_subagents() still sees them
    for item in deferred:
        await queue.put(item)

    if not updates:
        return state

    update_text = "\n\n".join(updates)
    new_message = SystemMessage(content=f"Subagent updates:\n{update_text}")

    log.info(f"Injected {len(updates)} subagent update(s) into executor state")
    # Return new state dict — pre-model hooks must not mutate state in-place
    return {**state, "messages": [*state.get("messages", []), new_message]}
