"""Close a detached stream that folds its cards into another run's message.

A background subagent and a background browser job each stream on a stream of
their own, which the client folds into the message of the turn that started
them (open_detached_stream with kind SUBAGENT). Closing one saves what it
streamed into that message by identity, then ends the stream.
"""

from pydantic import BaseModel, ConfigDict

from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_queue import close_detached_stream
from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import SavedSubagentGroup, ToolDataEntry
from shared.py.wide_events import log


async def close_folded_stream(
    stream_id: str, *, conversation_id: str, user_id: str, message_id: str | None
) -> None:
    """Save what the stream collected into the message it folded into, then end it."""
    try:
        entries = drain_executor_tool_data(stream_id)
        if entries and message_id:
            await _save_frames(conversation_id, user_id, message_id, entries)
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


class _SavedCard(BaseModel):
    """The identity of a saved approval_request entry."""

    model_config = ConfigDict(extra="ignore")

    approval_id: str = ""


async def _save_frames(
    conversation_id: str, user_id: str, message_id: str, entries: list[ToolDataEntry]
) -> None:
    """Persist a segment's frames by identity, so a reload shows one row and one card.

    A resumed segment's calls extend the row its park saved (in place, never read-
    modify-write), and a card already saved is settled there by the decision.
    """
    saved = await conversation_repository.get_message(conversation_id, message_id, user_id=user_id)
    if saved is None:
        log.error(
            f"{LogTag.AGENT} Detached stream cards matched no message; not saved",
            conversation_id=conversation_id,
            message_id=message_id,
            entries=len(entries),
        )
        return
    held: list[ToolDataEntry] = saved.tool_data or []
    held_groups = {
        SavedSubagentGroup.model_validate(e["data"]).subagent_id
        for e in held
        if e["tool_name"] == SUBAGENT_GROUP_TOOL_NAME
    }
    held_cards = {
        _SavedCard.model_validate(e["data"]).approval_id
        for e in held
        if e["tool_name"] == APPROVAL_REQUEST_TOOL_NAME
    }
    fresh: list[ToolDataEntry] = []
    for entry in entries:
        if entry["tool_name"] == SUBAGENT_GROUP_TOOL_NAME:
            group = SavedSubagentGroup.model_validate(entry["data"])
            if group.subagent_id in held_groups:
                await conversation_repository.extend_subagent_group(
                    conversation_id, user_id=user_id, message_id=message_id, group=group
                )
                continue
        elif (
            entry["tool_name"] == APPROVAL_REQUEST_TOOL_NAME
            and _SavedCard.model_validate(entry["data"]).approval_id in held_cards
        ):
            continue
        fresh.append(entry)
    if fresh and not await conversation_repository.append_message_tool_data(
        conversation_id, user_id=user_id, message_id=message_id, entries=fresh
    ):
        log.error(
            f"{LogTag.AGENT} Detached stream cards matched no message; not saved",
            conversation_id=conversation_id,
            message_id=message_id,
            entries=len(fresh),
        )
