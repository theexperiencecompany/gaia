"""A change to a conversation's list row tells the user's clients once, on real Mongo and real Redis.

The web's conversation list re-syncs only on this push or a reconnect (there is no
timer), so a list-visible write that does not push leaves every other tab's list stale.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.constants.chat import ConversationSource
from app.constants.conversation import CONVERSATION_LIST_CHANGED_EVENT
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_log_models import StopBy, StopRequested, UserMessage
from app.models.conversation_models import ConversationDocument
from app.services.conversation.mongo_log import MongoConversationLog
from tests.helpers import published_broadcasts


@pytest.fixture
def mongo_log(
    conversations_collection: object, real_redis: Redis
) -> Iterator[MongoConversationLog]:
    with patch("app.services.conversation_service.capture"):
        yield MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))


async def _conversation(user_id: str) -> str:
    conversation_id = f"c-{uuid4().hex}"
    await conversation_repository.create(
        ConversationDocument.model_validate(
            {"user_id": user_id, "conversation_id": conversation_id}
        )
    )
    return conversation_id


def _list_changed(user_id: str, conversation_id: str) -> dict[str, object]:
    return {
        "user_id": user_id,
        "message": {"type": CONVERSATION_LIST_CHANGED_EVENT, "conversation_id": conversation_id},
    }


async def test_a_new_message_pushes_one_list_change(
    mongo_log: MongoConversationLog, broadcast_channel: PubSub
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _conversation(user_id)

    await mongo_log.append(
        conversation_id, user_id, UserMessage(id="u1", text="hi", surface=ConversationSource.WEB)
    )

    assert await published_broadcasts(broadcast_channel, user_id) == [
        _list_changed(user_id, conversation_id)
    ]


async def test_an_entry_the_list_does_not_show_pushes_nothing(
    mongo_log: MongoConversationLog, broadcast_channel: PubSub
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _conversation(user_id)

    await mongo_log.append(conversation_id, user_id, StopRequested(id="s1", by=StopBy.USER))

    assert await published_broadcasts(broadcast_channel, user_id) == []


async def test_each_row_field_write_pushes_once(
    mongo_log: MongoConversationLog, broadcast_channel: PubSub
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _conversation(user_id)

    await conversation_repository.set_starred(conversation_id, user_id=user_id, starred=True)
    await conversation_repository.set_unread(conversation_id, user_id=user_id, unread=True)
    await conversation_repository.set_description(
        conversation_id, user_id=user_id, description="Trip plans"
    )

    assert (
        await published_broadcasts(broadcast_channel, user_id)
        == [_list_changed(user_id, conversation_id)] * 3
    )


async def test_a_write_that_matched_no_conversation_pushes_nothing(
    mongo_log: MongoConversationLog, broadcast_channel: PubSub
) -> None:
    user_id = str(ObjectId())
    await conversation_repository.set_starred("c-missing", user_id=user_id, starred=True)

    assert await published_broadcasts(broadcast_channel, user_id) == []
