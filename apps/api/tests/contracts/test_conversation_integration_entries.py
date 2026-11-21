"""IntegrationEntryRepository on real Mongo: a user's integration asks and connects across conversations."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.db.repositories.conversation_integration_entries import IntegrationEntryRepository
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import (
    IntegrationConnected,
    IntegrationNeeded,
)
from app.services.conversation.mongo_log import MongoConversationLog
from tests.contracts.conftest import HeldFlushes, create_conversation_head
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


def _needed(entry_id: str, integration_id: str = "gmail") -> IntegrationNeeded:
    return IntegrationNeeded(id=entry_id, integration_id=integration_id, integration_name="Mail")


def _connected(entry_id: str, needed_id: str) -> IntegrationConnected:
    return IntegrationConnected(
        id=entry_id, integration_id="gmail", integration_name="Mail", needed_id=needed_id
    )


async def test_the_users_entries_for_the_integration_since_the_cutoff_across_conversations(
    raw_collection: object, held: HeldFlushes
) -> None:
    clock = FakeClock()
    log = MongoConversationLog(ConversationLogRepository(), clock)
    first, second, foreign = "c-first", "c-second", "c-foreign"
    for conversation_id, user_id in ((first, UID), (second, UID), (foreign, "someone-else")):
        await create_conversation_head(conversation_id, user_id)
    await log.append(first, UID, _needed("old"))
    clock.advance(60)
    since = clock()
    await log.append(first, UID, _needed("n1"))
    await log.append(first, UID, user("u1"))
    await log.append(first, UID, _needed("other", integration_id="slack"))
    await log.append(first, UID, _connected("c1", needed_id="n1"))
    await log.append(second, UID, _needed("n2"))
    await log.append(foreign, "someone-else", _needed("theirs"))
    await held.run_all()
    for conversation_id, user_id in ((first, UID), (second, UID), (foreign, "someone-else")):
        await ConversationRepository().flush_outbox(conversation_id, user_id=user_id)

    found = await IntegrationEntryRepository().list_integration_entries(
        user_id=UID, integration_id="gmail", since=since
    )

    assert sorted((cid, logged.entry.id) for cid, logged in found) == [
        (first, "c1"),
        (first, "n1"),
        (second, "n2"),
    ]
    assert {type(logged.entry) for _, logged in found} == {IntegrationNeeded, IntegrationConnected}
    later = await IntegrationEntryRepository().list_integration_entries(
        user_id=UID, integration_id="gmail", since=since + timedelta(seconds=1)
    )
    assert later == []
