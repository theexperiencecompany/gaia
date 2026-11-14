"""Open and close a detached run's stream as logged work of its own.

A background subagent and a background browser job each stream on a stream of
their own, which outlives the turn that started them. Opening one logs a detached
WorkStarted keyed by the stream, so a Stop cancels it and state shows it; closing
it logs the cards its work recorded on that work's WorkFinished, then drops its session.
"""

from app.agents.core.background.executor_capture import session_approval_cards
from app.agents.core.background.run_stop import stop_requested
from app.agents.core.background.session import RunKind, create_session, teardown_session
from app.constants.log_tags import LogTag
from app.models.conversation_frame_models import ToolDataEvent
from app.models.conversation_log_models import WorkOutcome
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.work_deltas import work_cards
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
    create_session(stream_id, RunKind.QUEUED)
    return True


async def close_folded_stream(stream_id: str, *, conversation_id: str, user_id: str) -> None:
    """Log the run's end with the cards its stream collected, then drop its session."""
    cancelled = await stop_requested(stream_id)
    try:
        published = await work_cards(conversation_id, [stream_id])
        approvals = (ToolDataEvent(tool_data=card) for card in session_approval_cards(stream_id))
        cards = fold_cards(approvals, seed=published.tool_data)
        await record_work_finished(
            conversation_id,
            user_id,
            stream_id,
            WorkOutcome.CANCELLED if cancelled else WorkOutcome.DONE,
            WorkReport(
                text="", tool_data=cards.tool_data, nothing_for_user=True, image=published.image
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
        teardown_session(stream_id)
