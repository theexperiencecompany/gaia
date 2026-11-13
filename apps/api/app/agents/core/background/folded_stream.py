"""Close a detached run's stream, logging what it showed as that run's own finished work.

A background subagent and a background browser job each stream on a stream of
their own, which outlives the turn that started them. Their cards belong to that
run, not to any message: closing the stream logs them on a WorkFinished keyed by
the stream (work_log.record_detached_work), then ends the stream.
"""

from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_queue import close_detached_stream
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.services.conversation.work_log import record_detached_work
from shared.py.wide_events import log


async def close_folded_stream(stream_id: str, *, conversation_id: str, user_id: str) -> None:
    """Log what the stream collected as its run's finished work, then end it."""
    try:
        entries = drain_executor_tool_data(stream_id)
        if entries:
            await record_detached_work(conversation_id, user_id, stream_id, entries)
    except Exception as e:  # unlogged cards must not also cost the run its ending
        log.error(
            f"{LogTag.AGENT} Could not save a detached stream's cards",
            conversation_id=conversation_id,
            stream_id=stream_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        await close_detached_stream(
            stream_id, cancelled=await stream_manager.is_cancelled(stream_id)
        )
