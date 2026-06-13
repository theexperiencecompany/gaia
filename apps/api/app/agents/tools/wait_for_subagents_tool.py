"""Tool for executor to wait for background subagents to complete.

When the executor dispatches subagents with handoff(background=True), it
can continue with other work and then call wait_for_subagents() to block
until all background subagents have finished and stored their results.

Results are returned directly in the tool response so the executor can
formulate its final answer without needing a separate hook invocation.
"""

import asyncio
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import (
    drain_bg_subagent_results,
    get_pending_subagents,
)
from shared.py.wide_events import log


@tool
async def wait_for_subagents(
    config: RunnableConfig,
    # NOSONAR python:S7483 — `timeout` is part of this tool's LLM-facing input
    # schema (the model chooses how long to wait); it is not an internal call
    # timeout that an asyncio.timeout() context manager could replace.
    timeout: Annotated[  # NOSONAR python:S7483
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

    deadline = asyncio.get_running_loop().time() + timeout
    log.info(
        f"wait_for_subagents: waiting for {get_pending_subagents(stream_id)} "
        f"subagent(s) on stream {stream_id}"
    )

    # Poll until count hits zero or deadline passes. Subagents append their
    # result to _bg_subagent_results BEFORE decrementing, so a count of zero
    # guarantees all results are visible.
    while get_pending_subagents(stream_id) > 0:
        if asyncio.get_running_loop().time() >= deadline:
            log.warning(f"wait_for_subagents: timed out after {timeout}s")
            break
        await asyncio.sleep(0.1)

    results = drain_bg_subagent_results(stream_id)

    if not results:
        return "No background subagent results to collect."

    log.info(f"wait_for_subagents: collected {len(results)} result(s) for stream {stream_id}")
    return "\n\n---\n\n".join(f"[{item['agent']} result]\n{item['message']}" for item in results)


tools = [wait_for_subagents]
