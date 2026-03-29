"""Tool for executor to send progress updates to comms agent.

The executor LLM decides when something is worth reporting to the user.
This tool pushes the message to the comms inbox queue (looked up by
stream_id from configurable). A concurrent comms notifier loop reads
the queue and invokes the comms graph to generate a natural-language
response that is streamed to the user via SSE.

This is the GAIA equivalent of Claude Code's SendMessage tool.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_comms_inbox
from shared.py.wide_events import log


@tool
async def notify_comms(
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
    """Send an INTERMEDIATE progress update to the user while continuing your work.

    IMPORTANT: Do NOT use this for your final result. Your final response is
    automatically delivered to the user when you finish. This tool is ONLY for
    mid-execution progress updates when you have more work to do after the update.

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
        log.warning("notify_comms called without stream_id in configurable")
        return "No active stream — update not sent."

    queue = get_comms_inbox(stream_id)
    if not queue:
        log.warning(f"notify_comms: no comms inbox for stream {stream_id}")
        return "Comms inbox not available — update not sent."

    await queue.put({"type": "progress", "message": message})
    log.info(f"notify_comms: progress sent for stream {stream_id}")
    return "Progress update sent to user."


tools = [notify_comms]
