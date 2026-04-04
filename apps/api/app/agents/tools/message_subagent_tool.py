"""message_subagent tool — executor sends a message to a running background subagent.

The subagent drains this inbox via check_executor_inbox pre-model hook before
each LLM turn, so the message is injected as a SystemMessage into its state.

Only meaningful when the subagent is running concurrently in background mode
(handoff(background=True)). The inbox key matches the subagent thread_id
constructed by handoff_tools: f"{integration_id}_{executor_thread_id}".

Raises if the subagent inbox is not registered (subagent already completed).
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_subagent_inbox
from shared.py.wide_events import log


@tool
async def message_subagent(
    config: RunnableConfig,
    subagent_id: Annotated[
        str,
        "The integration ID of the target subagent (e.g., 'gmail', 'googlecalendar'). "
        "Must match the subagent_id passed to the handoff() call.",
    ],
    message: Annotated[
        str,
        "Message to send to the subagent. It will be injected into the subagent's "
        "context before its next LLM turn.",
    ],
) -> str:
    """Send a message to a currently-running background subagent.

    Use this to provide clarification, additional context, or instructions to a
    subagent that was dispatched with handoff(background=True). The subagent
    will receive the message before its next LLM invocation.

    Only works for background subagents. Raises an error if the subagent has
    already completed.
    """
    configurable = config.get("configurable", {})
    executor_thread_id = configurable.get("thread_id", "")
    subagent_key = f"{subagent_id}_{executor_thread_id}"

    queue = get_subagent_inbox(subagent_key)
    if queue is None:
        raise RuntimeError(
            f"Subagent '{subagent_id}' inbox is not registered (key={subagent_key!r}). "
            "The subagent may have already completed or was not started in background mode."
        )

    await queue.put({"type": "executor_message", "message": message})
    log.info(f"message_subagent: message queued for subagent '{subagent_id}' (key={subagent_key!r})")
    return f"Message sent to subagent '{subagent_id}'."
