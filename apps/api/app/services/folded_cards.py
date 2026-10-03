"""A detached run's cards, saved onto the message they fold into whichever is saved first.

A background subagent or browser job can end before the turn that started it has
saved its message. The cards then wait in Redis under that message's id, and the
second of the two writes merges them: a card close finding the turn's mark saves
them itself, the turn's save takes whatever is waiting. Each side writes its own
record before it reads the other's, so in any interleaving at least one of them
sees both, and the take is atomic, so a card is saved once.
"""

import json
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from redis.exceptions import ResponseError

from app.constants.cache import FOLDED_CARDS_PREFIX, FOLDED_CARDS_TTL
from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, SavedSubagentGroup, ToolDataEntry
from shared.py.wide_events import log


def _waiting_key(conversation_id: str, message_id: str) -> str:
    return f"{FOLDED_CARDS_PREFIX}{conversation_id}:{message_id}:cards"


def _saved_key(conversation_id: str, message_id: str) -> str:
    return f"{FOLDED_CARDS_PREFIX}{conversation_id}:{message_id}:saved"


async def save_folded_cards(
    conversation_id: str, user_id: str, message_id: str, entries: list[ToolDataEntry]
) -> None:
    """Save entries onto message_id now if it is saved, else leave them for its save."""
    saved = await conversation_repository.get_message(conversation_id, message_id, user_id=user_id)
    if saved is not None:
        await _save_frames(saved, conversation_id, user_id, message_id, entries)
        return
    log.info(
        f"{LogTag.AGENT} Detached stream cards wait for their message to be saved",
        conversation_id=conversation_id,
        message_id=message_id,
        entries=len(entries),
    )
    waiting = _waiting_key(conversation_id, message_id)
    client = redis_cache.client
    await client.rpush(waiting, *[json.dumps(entry) for entry in entries])
    await client.expire(waiting, FOLDED_CARDS_TTL)
    if await client.exists(_saved_key(conversation_id, message_id)):
        await _take_waiting(conversation_id, user_id, message_id)


async def fold_waiting_cards(conversation_id: str, user_id: str, message_id: str) -> None:
    """Mark message_id saved (by user_id), then save onto it the cards that ended before it was."""
    await redis_cache.client.set(
        _saved_key(conversation_id, message_id), user_id, ex=FOLDED_CARDS_TTL
    )
    await _take_waiting(conversation_id, user_id, message_id)


async def _take_waiting(conversation_id: str, user_id: str, message_id: str) -> None:
    """Take every card waiting for message_id, at most once, and save it there.

    RENAME moves the list out in one step, so of two takers only one gets it.
    """
    taken = f"{_waiting_key(conversation_id, message_id)}:taken:{uuid4().hex}"
    try:
        await redis_cache.client.rename(_waiting_key(conversation_id, message_id), taken)
    except ResponseError:
        return  # RENAME raises "no such key" only when nothing waits
    raw = await redis_cache.client.lrange(taken, 0, -1)
    await redis_cache.client.delete(taken)
    entries = [cast(ToolDataEntry, json.loads(item)) for item in raw]
    saved = await conversation_repository.get_message(conversation_id, message_id, user_id=user_id)
    if saved is None:
        log.error(
            f"{LogTag.AGENT} Detached stream cards matched no message; not saved",
            conversation_id=conversation_id,
            message_id=message_id,
            entries=len(entries),
        )
        return
    await _save_frames(saved, conversation_id, user_id, message_id, entries)


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
