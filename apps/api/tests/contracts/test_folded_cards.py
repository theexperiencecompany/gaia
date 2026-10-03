"""A detached run's cards reach their message whichever is saved first, against real Mongo.

The waiting room is the conversation document itself: a card close parks cards
there while the message is absent, and the append that saves the message takes
them in the same atomic pipeline update. These run the real repository and the
real save path, since the pipeline operators are Mongo's, not a double's.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
import uuid

import pytest

from app.constants.chat import FOLDED_CARDS_FIELD, FOLDED_CARDS_KEEP_SECONDS
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import ConversationRepository, conversation_repository
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationDocument
from app.services.folded_cards import save_folded_cards
from tests.helpers import captured_wide_event

CARD: dict[str, Any] = {"tool_name": "browser_result", "data": {"summary": "Booked."}}


@pytest.fixture
async def conversation(raw_collection: Any) -> ConversationDocument:
    doc = ConversationDocument.model_validate(
        {
            "user_id": f"u-{uuid.uuid4().hex}",
            "conversation_id": f"c-{uuid.uuid4().hex}",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    )
    await ConversationRepository().create(doc)
    return doc


async def _append(doc: ConversationDocument, message: MessageModel, **kw: Any) -> None:
    ids = await conversation_repository.append_messages(
        doc.conversation_id, user_id=doc.user_id, messages=[message], **kw
    )
    assert ids is not None


def _bot(message_id: str, **kw: Any) -> MessageModel:
    message = MessageModel(type="bot", response="On it.", **kw)
    message.message_id = message_id
    return message


async def _raw(raw_collection: Any, doc: ConversationDocument) -> dict[str, Any]:
    stored = await raw_collection.find_one({"conversation_id": doc.conversation_id})
    assert stored is not None
    return dict(stored)


async def _tool_data(doc: ConversationDocument, message_id: str) -> list[Any]:
    saved = await conversation_repository.get_message(
        doc.conversation_id, message_id, user_id=doc.user_id
    )
    assert saved is not None
    return list(saved.tool_data or [])


async def test_cards_for_a_saved_message_land_on_it(conversation: ConversationDocument) -> None:
    await _append(conversation, _bot("m1"))

    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [CARD])

    assert await _tool_data(conversation, "m1") == [CARD]


async def test_cards_that_end_first_wait_and_the_save_takes_them(
    conversation: ConversationDocument, raw_collection: Any
) -> None:
    own = {"tool_name": "search", "data": {"q": "x"}}
    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [CARD])
    waiting = (await _raw(raw_collection, conversation))[FOLDED_CARDS_FIELD]
    assert waiting["m1"]["cards"] == [CARD]

    await _append(conversation, _bot("m1", tool_data=[own]))

    assert await _tool_data(conversation, "m1") == [own, CARD]
    assert FOLDED_CARDS_FIELD not in await _raw(raw_collection, conversation)


async def test_a_message_saved_between_the_read_and_the_park_still_gets_its_cards(
    conversation: ConversationDocument,
) -> None:
    """The close reads "not saved", the turn saves, so the park must miss and the close retry."""
    real_get = conversation_repository.get_message
    reads: list[str] = []

    async def _read_then_the_turn_saves(
        conversation_id: str, message_id: str, *, user_id: str
    ) -> MessageModel | None:
        reads.append(message_id)
        if len(reads) == 1:
            await _append(conversation, _bot("m1"))
            return None
        return await real_get(conversation_id, message_id, user_id=user_id)

    with patch.object(conversation_repository, "get_message", _read_then_the_turn_saves):
        await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [CARD])

    assert await _tool_data(conversation, "m1") == [CARD]


async def test_a_close_and_a_save_racing_each_other_land_every_card_once(
    conversation: ConversationDocument, raw_collection: Any
) -> None:
    for n in range(12):
        card = {"tool_name": "step", "data": {"n": n}}
        close = save_folded_cards(
            conversation.conversation_id, conversation.user_id, f"m{n}", [card]
        )
        save = _append(conversation, _bot(f"m{n}"))
        await asyncio.gather(*((close, save) if n % 2 else (save, close)))

        assert await _tool_data(conversation, f"m{n}") == [card]
    assert FOLDED_CARDS_FIELD not in await _raw(raw_collection, conversation)


async def test_cards_for_a_conversation_that_does_not_exist_are_dropped_and_said(
    raw_collection: Any,
) -> None:
    async with captured_wide_event() as event:
        await save_folded_cards("c-gone", "u-gone", "m1", [CARD, CARD])

    assert await raw_collection.count_documents({}) == 0
    [error] = event["errors"]
    assert error["msg"] == (
        f"{LogTag.AGENT} Detached stream cards found no conversation to fold into; not saved"
    )
    assert (error["conversation_id"], error["message_id"], error["entries"]) == (
        "c-gone",
        "m1",
        2,
    )


async def test_text_that_looks_like_an_operator_is_stored_verbatim(
    conversation: ConversationDocument,
) -> None:
    message = MessageModel(type="user", response="$set me {$literal: 1} $$NOW")
    message.message_id = "m1"
    await _append(conversation, message)

    saved = await conversation_repository.get_message(
        conversation.conversation_id, "m1", user_id=conversation.user_id
    )
    assert saved is not None
    assert saved.response == "$set me {$literal: 1} $$NOW"
    assert saved.tool_data in (None, [])


async def test_the_history_cap_still_holds_when_a_save_takes_waiting_cards(
    conversation: ConversationDocument,
) -> None:
    await _append(conversation, _bot("m0"), max_messages=2)
    await _append(conversation, _bot("m1"), max_messages=2)
    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m2", [CARD])
    await _append(conversation, _bot("m2"), max_messages=2)

    fetched = await conversation_repository.get(
        conversation.conversation_id, user_id=conversation.user_id
    )
    assert fetched is not None
    assert [m.message_id for m in fetched.messages] == ["m1", "m2"]
    assert fetched.messages[1].tool_data == [CARD]


async def test_cards_waiting_a_day_for_a_message_never_saved_are_dropped_by_the_next_save(
    conversation: ConversationDocument, raw_collection: Any
) -> None:
    stale = datetime.now(UTC) - timedelta(seconds=FOLDED_CARDS_KEEP_SECONDS + 60)
    await raw_collection.update_one(
        {"conversation_id": conversation.conversation_id},
        {
            "$set": {
                FOLDED_CARDS_FIELD: {
                    "abandoned": {"since": stale, "cards": [CARD]},
                    "pending": {"since": datetime.now(UTC), "cards": [CARD]},
                }
            }
        },
    )

    await _append(conversation, _bot("other"))

    waiting = (await _raw(raw_collection, conversation))[FOLDED_CARDS_FIELD]
    assert set(waiting) == {"pending"}


async def test_readers_never_see_the_waiting_room(
    conversation: ConversationDocument,
) -> None:
    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [CARD])

    fetched = await conversation_repository.get(
        conversation.conversation_id, user_id=conversation.user_id
    )
    assert fetched is not None
    assert "m1" in fetched.folded_cards
    assert FOLDED_CARDS_FIELD not in fetched.model_dump()
    assert FOLDED_CARDS_FIELD not in fetched.model_dump(mode="json")


async def test_two_runs_ending_before_the_message_both_land_on_it(
    conversation: ConversationDocument,
) -> None:
    other = {"tool_name": "subagent_group", "data": {"subagent_id": "row-2"}}
    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [CARD])
    await save_folded_cards(conversation.conversation_id, conversation.user_id, "m1", [other])

    await _append(conversation, _bot("m1"))

    assert await _tool_data(conversation, "m1") == [CARD, other]


async def test_cards_never_wait_on_another_users_conversation(
    conversation: ConversationDocument, raw_collection: Any
) -> None:
    async with captured_wide_event() as event:
        await save_folded_cards(conversation.conversation_id, "someone-else", "m1", [CARD])

    assert FOLDED_CARDS_FIELD not in await _raw(raw_collection, conversation)
    [error] = event["errors"]
    assert error["msg"].endswith("found no conversation to fold into; not saved")
