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

from app.agents.core.background.session import get_session
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.utils.background_tasks import spawn_background_task

#: Task name for the fire-and-forget stream publishes. Tests drain by this name
#: to wait out exactly the XADDs a turn scheduled, rather than every background
#: task in the process (some of which outlive any single turn).
STREAM_PUBLISH_TASK_NAME = "stream-publish"
from shared.py.wide_events import log


def make_redis_stream_writer(stream_id: str) -> Callable[[dict[str, Any]], None]:
    """Return a sync callable that publishes tool events directly to Redis.

    Matches the stream_writer protocol expected by execute_subagent_stream().
    Safe to call from sync code running inside an async context.

    Also appends each event to the stream session's tool-event collector (if a
    session is registered) so chat_service can capture executor tool_data /
    tool_output / todo_progress for MongoDB persistence after the notifier
    returns. The SSE publish happens regardless — the session is a side-channel
    only for the save path, not for re-publishing.
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
            session.tool_events.append(data)

    return writer
