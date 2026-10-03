"""Close a detached stream that folds its cards into another run's message.

A background subagent and a background browser job each stream on a stream of
their own, which the client folds into the message of the turn that started
them (open_detached_stream with kind SUBAGENT). Closing one saves what it
streamed into that message (folded_cards, whichever of the two is saved first),
then ends the stream.
"""

from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_queue import close_detached_stream
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.services.folded_cards import save_folded_cards
from shared.py.wide_events import log


async def close_folded_stream(
    stream_id: str, *, conversation_id: str, user_id: str, message_id: str | None
) -> None:
    """Save what the stream collected into the message it folded into, then end it."""
    try:
        entries = drain_executor_tool_data(stream_id)
        if entries and message_id:
            await save_folded_cards(conversation_id, user_id, message_id, entries)
        elif entries:
            log.warning(
                f"{LogTag.AGENT} Detached stream has no message to save its cards into",
                conversation_id=conversation_id,
                stream_id=stream_id,
                entries=len(entries),
            )
    except Exception as e:  # unsaved cards must not also cost the run its ending
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
