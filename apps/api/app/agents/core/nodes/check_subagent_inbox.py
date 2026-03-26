"""Pre-model hook that drains the executor inbox at each turn boundary.

Runs before every executor LLM invocation. If subagents have pushed
progress updates or results via notify_executor or background handoffs,
they are injected into the executor's state so the LLM can process them
and optionally call notify_comms to forward to the user.

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
    """Drain executor inbox and inject subagent messages into state."""
    configurable = config.get("configurable", {})
    stream_id = configurable.get("stream_id")

    if not stream_id:
        return state

    queue = get_executor_inbox(stream_id)
    if not queue:
        return state

    # Non-blocking drain: get all available messages
    updates = []
    while True:
        try:
            item = queue.get_nowait()
            msg_type = item.get("type", "subagent_update")
            agent = item.get("agent", "subagent")
            message = item.get("message", "")
            if msg_type == "subagent_result":
                updates.append(f"[SUBAGENT_RESULT from {agent}]\n{message}")
            else:
                updates.append(f"[SUBAGENT_UPDATE from {agent}]\n{message}")
        except asyncio.QueueEmpty:
            break

    if not updates:
        return state

    update_text = "\n\n".join(updates)
    messages = state.get("messages", [])
    messages.append(SystemMessage(content=f"Subagent messages:\n{update_text}"))

    log.info(f"Injected {len(updates)} subagent message(s) into executor state")
    return state
