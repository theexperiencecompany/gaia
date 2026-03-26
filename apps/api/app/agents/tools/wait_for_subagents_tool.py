"""Tool for executor to wait for background subagents to complete.

When the executor dispatches subagents with handoff(background=True), it
can continue with other work and then call wait_for_subagents() to block
until all background subagents have pushed their results to executor_inbox.

Results are returned directly in the tool response so the executor can
formulate its final answer without needing a separate hook invocation.
"""

import asyncio
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import (
    get_executor_inbox,
    get_pending_subagents,
)
from shared.py.wide_events import log


@tool
async def wait_for_subagents(
    config: RunnableConfig,
    timeout: Annotated[
        int,
        "Maximum seconds to wait for all background subagents. Default 120.",
    ] = 120,
) -> str:
    """Wait for all pending background subagents to complete and return their results.

    Call this after dispatching subagents with handoff(background=True) and
    after finishing any parallel work that doesn't depend on their results.

    Returns all subagent results concatenated, ready for you to summarize.
    Returns immediately if no background subagents are pending.
    """
    configurable = config.get("configurable", {})
    stream_id = configurable.get("stream_id")

    if not stream_id:
        return "No active stream — cannot wait for subagents."

    pending = get_pending_subagents(stream_id)
    queue = get_executor_inbox(stream_id)

    if pending == 0 and (queue is None or queue.empty()):
        return "No background subagents pending."

    if queue is None:
        return "Executor inbox not available."

    log.info(
        f"wait_for_subagents: waiting for {pending} subagent(s) on stream {stream_id}"
    )

    results: list[str] = []
    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            log.warning(f"wait_for_subagents: timed out after {timeout}s")
            break

        try:
            item = await asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
        except asyncio.TimeoutError:
            # No item arrived — check if all subagents are done
            if get_pending_subagents(stream_id) == 0:
                _drain_remaining(queue, results)
                break
            continue

        if item is None:
            break

        agent = item.get("agent", "subagent")
        message = item.get("message", "")
        msg_type = item.get("type", "")

        if msg_type == "subagent_result":
            results.append(f"[{agent} result]\n{message}")
        elif msg_type == "subagent_update":
            results.append(f"[{agent} update]\n{message}")

        # All subagents done and queue now empty → exit
        if get_pending_subagents(stream_id) == 0:
            _drain_remaining(queue, results)
            break

    if not results:
        return "Timed out waiting for background subagents — no results received."

    log.info(
        f"wait_for_subagents: collected {len(results)} result(s) for stream {stream_id}"
    )
    return "\n\n---\n\n".join(results)


def _drain_remaining(queue: asyncio.Queue[Any], results: list[str]) -> None:
    """Non-blocking drain of any remaining items already in the queue."""
    while True:
        try:
            item = queue.get_nowait()
            if item is None:
                break
            agent = item.get("agent", "subagent")
            message = item.get("message", "")
            msg_type = item.get("type", "")
            if msg_type == "subagent_result":
                results.append(f"[{agent} result]\n{message}")
            elif msg_type == "subagent_update":
                results.append(f"[{agent} update]\n{message}")
        except asyncio.QueueEmpty:
            break


tools = [wait_for_subagents]
