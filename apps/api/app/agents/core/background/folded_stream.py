"""Open and close a detached run's stream as logged work of its own.

A background subagent and a background browser job each stream on a stream of
their own, which outlives the turn that started them. Opening one logs a detached
WorkStarted keyed by the stream, so a Stop cancels it and state shows it; closing
it logs the cards it showed on that work's WorkFinished, then ends the stream.
"""

from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_queue import close_detached_stream, open_detached_stream
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.models.conversation_log_models import WorkOutcome
from app.services.conversation.work_log import (
    WorkReport,
    record_work_carried,
    record_work_finished,
)
from shared.py.wide_events import log


async def open_folded_stream(stream_id: str, *, conversation_id: str, user_id: str) -> bool:
    """Log the run as detached work and open its stream; False when a Stop refuses it, so it must not run."""
    if not await record_work_carried(conversation_id, user_id, stream_id, detached=True):
        return False
    await open_detached_stream(stream_id, conversation_id=conversation_id, user_id=user_id)
    return True


async def close_folded_stream(stream_id: str, *, conversation_id: str, user_id: str) -> None:
    """Log the run's end with the cards its stream collected, then end the stream."""
    cancelled = await stream_manager.is_cancelled(stream_id)
    try:
        await record_work_finished(
            conversation_id,
            user_id,
            stream_id,
            WorkOutcome.CANCELLED if cancelled else WorkOutcome.DONE,
            WorkReport(
                text="", tool_data=drain_executor_tool_data(stream_id), nothing_for_user=True
            ),
        )
    except Exception as e:  # unlogged cards must not also cost the run its ending
        log.error(
            f"{LogTag.AGENT} Could not log a detached run's end",
            conversation_id=conversation_id,
            stream_id=stream_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        await close_detached_stream(stream_id, cancelled=cancelled)
