"""message_comms tool — executor sends a progress update to the comms agent.

Pushes to the comms inbox queue (keyed by stream_id). The comms notifier loop
drains the queue and passes it to the comms agent (AI layer), which generates
a natural-language response and streams it to the user via SSE.

executor → comms agent (AI) → user

Raises if the comms inbox is not registered (stream already closed/done).
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_comms_inbox
from shared.py.wide_events import log


@tool
async def message_comms(
    config: RunnableConfig,
    message: Annotated[
        str,
        "Progress update for the user. Be factual and specific — include names, "
        "counts, IDs. Comms will handle tone and style. Examples: "
        "'Found 2 of 3 emails: Invoice from Acme ($450), Payment from Stripe.' "
        "'Created 3 calendar events for next week.' "
        "'Gmail search returned no results for that query, trying broader search.'",
    ],
) -> str:
    """Send an INTERMEDIATE progress update to the comms agent while continuing your work.

    The comms agent (AI) receives your update, generates a natural-language response,
    and delivers it to the user. Your final result is sent automatically when you finish —
    this tool is ONLY for mid-execution updates when you have more work to do.

    Use this when:
    - You complete a significant subtask AND have more work to do
    - You have partial results and more work is pending
    - You encounter an issue that changes the approach
    - You're about to start a long operation the user should know about

    Do NOT use for:
    - Your final result or summary (this is sent automatically)
    - Every single tool call (too noisy)
    - Internal bookkeeping (plan_tasks, retrieve_tools, vfs operations)
    - Trivial or expected intermediate steps
    """
    configurable = config.get("configurable", {})
    stream_id = configurable.get("stream_id")

    if not stream_id:
        return "No active stream — message not sent."

    queue = get_comms_inbox(stream_id)
    if not queue:
        raise RuntimeError(
            f"Comms inbox for stream '{stream_id}' is not registered. "
            "The stream may have already closed."
        )

    await queue.put({"type": "progress", "message": message})
    log.info(f"message_comms: progress sent for stream {stream_id}")
    return "Progress update sent to user."


tools = [message_comms]
