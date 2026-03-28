"""Sync-callable Redis stream writer for background executor execution.

When executor runs as a background asyncio task (outside LangGraph's
graph context), get_stream_writer() is unavailable. This provides a
sync callable that schedules async Redis publishes via asyncio.create_task.

Usage:
    writer = make_redis_stream_writer(stream_id)
    result = await execute_subagent_stream(ctx=ctx, stream_writer=writer)
"""

import asyncio
import json
from typing import Any, Callable

from shared.py.wide_events import log

from app.agents.core.background.inbox import get_tool_event_collector
from app.core.stream_manager import stream_manager


def make_redis_stream_writer(stream_id: str) -> Callable[[dict[str, Any]], None]:
    """Return a sync callable that publishes tool events directly to Redis.

    Matches the stream_writer protocol expected by execute_subagent_stream().
    Safe to call from sync code running inside an async context.

    Also appends each event to the registered tool event collector (if any)
    so chat_service can capture executor tool_data / tool_output /
    todo_progress for MongoDB persistence after the notifier returns.
    The SSE publish happens regardless — the collector is a side-channel
    only for the save path, not for re-publishing.
    """

    def writer(data: dict[str, Any]) -> None:
        chunk = f"data: {json.dumps(data)}\n\n"
        try:
            asyncio.create_task(stream_manager.publish_chunk(stream_id, chunk))
        except RuntimeError:
            log.error(f"redis_writer: no event loop for stream {stream_id}")

        collector = get_tool_event_collector(stream_id)
        if collector is not None:
            collector.append(data)

    return writer
