"""Background subagent coroutine for non-blocking handoff execution.

Spawned by handoff(background=True) via asyncio.create_task(). Runs the
subagent graph, pushes the final result to executor_inbox, and decrements
the pending subagent counter.

The executor calls wait_for_subagents() to block until all background
subagents complete and collect their results.
"""

import asyncio
import time
from typing import Any, Optional

from shared.py.wide_events import log

from app.agents.core.background.inbox import decrement_pending_subagents, deregister_subagent_inbox
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
)
from app.utils.agent_utils import (
    IntegrationMetadata,
    format_subagent_end_event,
    format_subagent_start_event,
)


async def run_subagent_background(
    ctx: SubagentExecutionContext,
    stream_id: str,
    executor_inbox: asyncio.Queue[Any],
    subagent_thread_id: Optional[str] = None,
    integration_metadata: Optional[IntegrationMetadata] = None,
    subagent_id: Optional[str] = None,
    display_name: Optional[str] = None,
    tool_category: Optional[str] = None,
    icon_url: Optional[str] = None,
) -> None:
    """Run a provider subagent in the background and push result to executor_inbox.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed to executor_inbox as subagent_result errors.

    Args:
        ctx: Fully prepared SubagentExecutionContext.
        stream_id: Active SSE stream ID for tool event publishing.
        executor_inbox: Queue to push result for the executor to read.
        integration_metadata: Optional icon/name metadata for tool events.
    """
    try:
        writer = make_redis_stream_writer(stream_id)

        if subagent_id:
            writer(
                {
                    "subagent_start": format_subagent_start_event(
                        subagent_name=display_name or ctx.agent_name,
                        agent_type="handoff",
                        subagent_id=subagent_id,
                        icon_url=icon_url,
                        tool_category=tool_category,
                    )
                }
            )

        start_time = time.monotonic()
        result = await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=integration_metadata,
            subagent_id=subagent_id,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        if subagent_id:
            writer(
                {
                    "subagent_end": format_subagent_end_event(
                        subagent_id=subagent_id,
                        duration_ms=duration_ms,
                    )
                }
            )
        log.info(
            f"Background subagent {ctx.agent_name} completed for stream {stream_id}"
        )
        await executor_inbox.put(
            {
                "type": "subagent_result",
                "message": result,
                "agent": ctx.agent_name,
            }
        )
    except Exception as e:
        log.error(
            f"Background subagent {ctx.agent_name} failed for stream {stream_id}: {e}"
        )
        await executor_inbox.put(
            {
                "type": "subagent_result",
                "message": f"Error from {ctx.agent_name}: {str(e)}",
                "agent": ctx.agent_name,
            }
        )
    finally:
        decrement_pending_subagents(stream_id)
        if subagent_thread_id:
            deregister_subagent_inbox(subagent_thread_id)
