"""Sync-callable Redis stream writer for background executor execution.

When executor runs as a background asyncio task (outside LangGraph's
graph context), get_stream_writer() is unavailable. This provides a
sync callable that schedules async Redis publishes via asyncio.create_task.

Usage:
    writer = make_redis_stream_writer(stream_id)
    result = await execute_subagent_stream(ctx=ctx, stream_writer=writer)
"""

from collections.abc import Callable
import json
from typing import Any

from app.agents.core.background.session import StreamSession, get_session
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.utils.background_tasks import spawn_background_task

#: Task name for the fire-and-forget stream publishes. Tests drain by this name
#: to wait out exactly the XADDs a turn scheduled, rather than every background
#: task in the process (some of which outlive any single turn).
STREAM_PUBLISH_TASK_NAME = "stream-publish"
from shared.py.wide_events import log


def _collect(session: StreamSession, data: dict[str, Any]) -> None:
    """Append an event to the session collector, coalescing reasoning deltas.

    Reasoning arrives one event per model chunk — effectively per token — and
    everything in this list is persisted onto the message verbatim, which is how
    one production conversation ended up carrying ~22k reasoning entries. The
    frontend renders a step's thinking as one block regardless.

    So the collector keeps ONE entry per contiguous run of thinking: any other
    event between two deltas (a tool call announced, a tool result, a subagent
    boundary) closes the block, and the end of the run closes the last one by
    simply never extending it. Deltas are still published individually above —
    the live stream must stay token by token; only what gets persisted is
    batched. Same-``subagent_id`` only, so two subagents thinking concurrently
    on one stream never merge into each other.
    """
    reasoning = data.get("reasoning")
    if not isinstance(reasoning, dict):
        session.tool_events.append(data)
        return
    previous = session.tool_events[-1].get("reasoning") if session.tool_events else None
    if isinstance(previous, dict) and previous.get("subagent_id") == reasoning.get("subagent_id"):
        previous["content"] = f"{previous.get('content', '')}{reasoning.get('content', '')}"
        return
    # A copy: the published dict belongs to the caller, and the merge above
    # mutates whatever is stored here on every subsequent delta.
    session.tool_events.append({"reasoning": dict(reasoning)})


def make_redis_stream_writer(stream_id: str) -> Callable[[dict[str, Any]], None]:
    """Return a sync callable that publishes tool events directly to Redis.

    Matches the stream_writer protocol expected by execute_subagent_stream().
    Safe to call from sync code running inside an async context.

    Also appends each event to the stream session's tool-event collector (if a
    session is registered) so chat_service can capture executor tool_data /
    tool_output / todo_progress for MongoDB persistence after the notifier
    returns. The SSE publish happens regardless — the session is a side-channel
    only for the save path, not for re-publishing — and it publishes every event
    verbatim, including each reasoning delta, which ``_collect`` coalesces for
    the save path alone.
    """

    def writer(data: dict[str, Any]) -> None:
        chunk = f"data: {json.dumps(data)}\n\n"
        try:
            spawn_background_task(
                stream_manager.publish_chunk(stream_id, chunk),
                name=STREAM_PUBLISH_TASK_NAME,
            )
        except RuntimeError:
            log.error(f"{LogTag.AGENT} redis_writer: no event loop for stream", stream_id=stream_id)

        session = get_session(stream_id)
        if session is not None:
            _collect(session, data)

    return writer
