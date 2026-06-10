"""Background subagent coroutine for non-blocking handoff execution.

Spawned by handoff(background=True) via asyncio.create_task(). Runs the
subagent graph, appends the final result to the per-stream
_bg_subagent_results bucket, and decrements the pending subagent counter.

The executor calls wait_for_subagents() to block until all background
subagents complete and to collect their results.
"""

import time

from app.agents.core.background.inbox import (
    append_bg_subagent_result,
    decrement_pending_subagents,
)
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
from shared.py.wide_events import log


async def run_subagent_background(
    ctx: SubagentExecutionContext,
    stream_id: str,
    integration_metadata: IntegrationMetadata | None = None,
    subagent_id: str | None = None,
    display_name: str | None = None,
    tool_category: str | None = None,
    icon_url: str | None = None,
) -> None:
    """Run a provider subagent in the background and store its result.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and stored as the subagent's result text.

    Args:
        ctx: Fully prepared SubagentExecutionContext.
        stream_id: Active SSE stream ID for tool event publishing.
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
            "Background subagent completed",
            agent_name=ctx.agent_name,
            stream_id=stream_id,
        )
        append_bg_subagent_result(stream_id, ctx.agent_name, result)
    except Exception as e:
        log.error(
            "Background subagent failed",
            agent_name=ctx.agent_name,
            stream_id=stream_id,
            error=str(e),
        )
        append_bg_subagent_result(
            stream_id,
            ctx.agent_name,
            f"Error from {ctx.agent_name}: {e!s}",
        )
    finally:
        # Decrement AFTER appending the result so any wait_for_subagents
        # that wakes up on the count change always sees the result.
        decrement_pending_subagents(stream_id)
