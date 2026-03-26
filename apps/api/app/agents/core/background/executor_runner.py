"""Background executor coroutine.

Spawned by call_executor tool via asyncio.create_task(). Runs the executor
agent graph with a Redis stream writer for tool events, then pushes the
final result + sentinel to the comms inbox so the notifier can generate
the comms response.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

import asyncio
from datetime import datetime
from typing import Optional

from shared.py.wide_events import log

from app.agents.core.background.inbox import (
    deregister_executor_inbox,
    register_executor_inbox,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.db.redis import redis_cache


async def run_executor_background(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str,
    conversation_id: str,
    comms_inbox: Optional[asyncio.Queue] = None,
) -> None:
    """Run executor agent in background and push result to comms inbox.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed to comms_inbox so the notifier can inform the user.

    Args:
        task: Task string from comms to executor.
        configurable: RunnableConfig.configurable dict.
        user_time: User's local time.
        stream_id: Active SSE stream ID for tool event publishing.
        conversation_id: Conversation ID used as the Redis lock key.
        comms_inbox: Queue to push progress/final results for comms notifier.
    """
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"

    # Register executor inbox for subagent → executor communication
    register_executor_inbox(stream_id)

    try:
        ctx, error = await prepare_executor_execution(
            task=task,
            configurable=configurable,
            user_time=user_time,
            stream_id=stream_id,
        )

        if error or ctx is None:
            msg = error or "Executor agent not available"
            log.error(f"Background executor prep failed: {msg}")
            if comms_inbox:
                await comms_inbox.put({"type": "error", "message": msg})
            return

        writer = make_redis_stream_writer(stream_id)
        result = await execute_subagent_stream(ctx=ctx, stream_writer=writer)

        log.info(f"Background executor completed for stream {stream_id}")

        # Push final result to comms inbox
        if comms_inbox:
            await comms_inbox.put({"type": "final", "message": result})

    except Exception as e:
        log.error(f"Background executor failed for stream {stream_id}: {e}")
        if comms_inbox:
            await comms_inbox.put({"type": "error", "message": str(e)})
    finally:
        # Always release lock and signal notifier to stop
        await redis_cache.delete(lock_key)
        deregister_executor_inbox(stream_id)
        if comms_inbox:
            await comms_inbox.put(None)  # sentinel — notifier loop exits
