"""Generic self-pause tool: lets the agent wait out a long-running task instead
of polling the same call in a tight loop and exhausting the recursion limit."""

import asyncio
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.general import MAX_WAIT_SECONDS, WAIT_POLL_INTERVAL_SECONDS
from app.core.stream_manager import stream_manager
from shared.py.wide_events import log


@tool
async def wait(
    config: RunnableConfig,
    # NOSONAR python:S7483 — `seconds` is part of this tool's LLM-facing input
    # schema (the model chooses how long to pause); it is not an internal call
    # timeout that an asyncio.timeout() context manager could replace.
    seconds: Annotated[  # NOSONAR python:S7483
        float,
        "How long to pause before continuing, in seconds. Pick a value that "
        "matches how long the in-progress task realistically needs (e.g. 60 "
        f"for a ~1 minute render). Capped at {MAX_WAIT_SECONDS}s per call.",
    ],
    reason: Annotated[
        str | None,
        'Short reason shown to the user while waiting (e.g. "waiting for the '
        'render to finish"). Optional.',
    ] = None,
) -> str:
    """Pause execution for a set duration, then resume.

    Use this when a task is genuinely in progress and you must wait before
    checking it again: a long render/build/export, an async job that reports
    progress, a background process. Pausing once and re-checking afterwards is
    far better than calling the same tool repeatedly in a tight loop.

    Returns once the wait elapses (or immediately if the user cancels the turn).
    """
    seconds = max(0.0, min(seconds, MAX_WAIT_SECONDS))

    writer = get_stream_writer()
    writer({"progress": f"Waiting {seconds:.0f}s" + (f" ({reason})" if reason else "") + "..."})

    stream_id = config.get("configurable", {}).get("stream_id")
    log.info(f"wait: pausing {seconds:.1f}s (reason={reason!r}, stream={stream_id})")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        if stream_id and await stream_manager.is_cancelled(stream_id):
            log.info(f"wait: cancelled by user mid-wait (stream={stream_id})")
            return "Wait cancelled by user."
        await asyncio.sleep(min(WAIT_POLL_INTERVAL_SECONDS, remaining))

    return f"Waited {seconds:.0f}s. Resume and re-check the task."


tools = [wait]
