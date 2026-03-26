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

from app.core.stream_manager import stream_manager

# Prevent GC of in-flight publish tasks (asyncio.create_task is weakly referenced)
_publish_tasks: set[asyncio.Task[None]] = set()


def make_redis_stream_writer(stream_id: str) -> Callable[[dict[str, Any]], None]:
    """Return a sync callable that publishes tool events directly to Redis.

    Matches the stream_writer protocol expected by execute_subagent_stream().
    Safe to call from sync code running inside an async context.
    """

    def writer(data: dict[str, Any]) -> None:
        chunk = f"data: {json.dumps(data)}\n\n"
        try:
            task = asyncio.create_task(stream_manager.publish_chunk(stream_id, chunk))
            _publish_tasks.add(task)
            task.add_done_callback(_publish_tasks.discard)
        except RuntimeError:
            log.error(f"redis_writer: no event loop for stream {stream_id}")

    return writer
