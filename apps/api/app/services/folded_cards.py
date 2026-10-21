"""A detached run's cards, saved onto the message they fold into whichever is saved first.

A background subagent or browser job can end before the turn that started it has
saved its message. Its cards then wait on the conversation document itself, and
the append that saves the message absorbs them in the same atomic update. Both
writes are single-document Mongo updates, so neither order loses a card or saves
one twice, and a turn's save never depends on a second store.
"""

from pydantic import BaseModel, ConfigDict

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, SavedSubagentGroup, ToolDataEntry
from shared.py.wide_events import log

#: Save-or-park attempts: a miss on both means the message appeared in between,
#: so the next attempt finds it; missing on every one means no conversation.
_FOLD_ATTEMPTS = 3


async def save_folded_cards(
    conversation_id: str, user_id: str, message_id: str, entries: list[ToolDataEntry]
) -> None:
    """Save entries onto message_id if it is saved, else leave them for its save to take."""
    for _ in range(_FOLD_ATTEMPTS):
        saved = await conversation_repository.get_message(
            conversation_id, message_id, user_id=user_id
        )
        if saved is not None:
            await _save_frames(saved, conversation_id, user_id, message_id, entries)
            return
        if await conversation_repository.park_folded_cards(
            conversation_id, user_id=user_id, message_id=message_id, entries=entries
        ):
            log.info(
                f"{LogTag.AGENT} Detached stream cards wait for their message to be saved",
                conversation_id=conversation_id,
                message_id=message_id,
                entries=len(entries),
            )
            return
    log.error(
        f"{LogTag.AGENT} Detached stream cards found no conversation to fold into; not saved",
        conversation_id=conversation_id,
        message_id=message_id,
        entries=len(entries),
    )


class _SavedCard(BaseModel):
    """The identity of a saved approval_request entry."""

    model_config = ConfigDict(extra="ignore")

    approval_id: str = ""


async def _save_frames(
    saved: MessageModel,
    conversation_id: str,
    user_id: str,
    message_id: str,
    entries: list[ToolDataEntry],
) -> None:
    """Persist a segment's frames onto saved by identity, so a reload shows one row and one card.

    A resumed segment's calls extend the row its park saved (in place, never read-
    modify-write), and a card already saved is settled there by the decision.
    """
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
