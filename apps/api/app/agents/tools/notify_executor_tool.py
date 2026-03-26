"""Tool for subagents to send progress updates to the executor agent."""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_executor_inbox
from shared.py.wide_events import log


@tool
async def notify_executor(
    config: RunnableConfig,
    message: Annotated[
        str,
        "Progress update for the executor. Be factual and specific — include "
        "names, counts, IDs, status. The executor will decide whether to "
        "forward this to the user.",
    ],
) -> str:
    """Send a progress update to the executor agent while continuing your work.

    Use this when you complete a significant subtask or have partial results.
    The executor will decide whether to notify the user.
    """
    configurable = config.get("configurable", {})
    stream_id = configurable.get("stream_id")

    if not stream_id:
        return "No active stream — update not sent."

    queue = get_executor_inbox(stream_id)
    if not queue:
        return "Executor inbox not available — update not sent."

    await queue.put({"type": "subagent_update", "message": message})
    log.info(f"notify_executor: update sent for stream {stream_id}")
    return "Progress update sent to executor."


tools = [notify_executor]
