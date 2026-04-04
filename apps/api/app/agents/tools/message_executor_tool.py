"""message_executor tool — subagent sends a progress update to the executor.

Pushes to the executor inbox queue (keyed by stream_id). The executor's
check_subagent_inbox pre-model hook drains it before each LLM turn and
injects updates as a SystemMessage so the executor can relay them to the user.

Raises if the executor inbox is not registered (executor already done).
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_executor_inbox
from shared.py.wide_events import log


@tool
async def message_executor(
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
        return "No active stream — message not sent."

    queue = get_executor_inbox(stream_id)
    if not queue:
        raise RuntimeError(
            f"Executor inbox for stream '{stream_id}' is not registered. "
            "The executor may have already completed."
        )

    await queue.put({"type": "subagent_update", "message": message})
    log.info(f"message_executor: update sent for stream {stream_id}")
    return "Progress update sent to executor."


tools = [message_executor]
