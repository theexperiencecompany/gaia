"""Pre-model hook that drains the subagent inbox before each LLM turn.

Runs inside subagents before every LLM invocation. If the executor has
sent messages via message_subagent, they are injected into the subagent's
state as a SystemMessage so the LLM can act on them.

The inbox key is the subagent's own thread_id, which matches what
handoff_tools registers: f"{integration_id}_{executor_thread_id}".
"""

import asyncio
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.core.background.inbox import get_subagent_inbox
from shared.py.wide_events import log


async def check_executor_inbox(
    state: Any,
    config: RunnableConfig,
    store: BaseStore,
) -> Any:
    """Drain executor_message entries from the subagent inbox into state."""
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id", "")

    if not thread_id:
        return state

    queue = get_subagent_inbox(thread_id)
    if not queue:
        return state

    messages: list[str] = []
    while True:
        try:
            item = queue.get_nowait()
            message = item.get("message", "")
            if message:
                messages.append(message)
        except asyncio.QueueEmpty:
            break

    if not messages:
        return state

    text = "\n\n".join(messages)
    new_message = SystemMessage(content=f"[MESSAGE FROM EXECUTOR]:\n{text}")

    log.info(f"check_executor_inbox: injected {len(messages)} executor message(s) into subagent state")
    return {**state, "messages": [*state.get("messages", []), new_message]}
