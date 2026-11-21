"""LogAmendRepository on real Mongo: fenced and unfenced amendments, and pins, as the stored entry sees them."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.chat import CONVERSATION_APPEND_MAX_ATTEMPTS
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversation_log_amends import LogAmendRepository
from app.models.conversation_log_models import LoggedEntry, Reply, UserMessage
from app.services.conversation.mongo_log import MongoConversationLog
from app.utils.errors import ConversationStoreError
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import notice, opened, user
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


async def _noop() -> None:
    return None


async def _appended(log: MongoConversationLog, conversation: str, held: HeldFlushes) -> LoggedEntry:
    appended = await log.append(conversation, UID, user("u1"))
    await held.run_all()
    held.spawned.clear()
    return appended.logged


def _edited(logged: LoggedEntry, text: str, revision: int = 1) -> LoggedEntry:
    entry = logged.entry
    assert isinstance(entry, UserMessage)
    return logged.model_copy(
        update={"entry": entry.model_copy(update={"text": text, "revision": revision})}
    )


async def _flushed(
    raw_collection: Any, entries_collection: Any, conversation: str, seq: int = 1
) -> dict[str, Any]:
    """Return the entry document the flush wrote, once the head's outbox no longer holds it."""
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert str(seq) not in (head.get("outbox") or {})
    stored = await entries_collection.find_one({"conversation_id": conversation, "seq": seq})
    assert stored is not None
    return stored


async def test_a_fenced_amend_lands_only_for_the_epoch_holding_the_step(
    log: MongoConversationLog,
    conversation: str,
    raw_collection: Any,
    held: HeldFlushes,
    entries_collection: Any,
) -> None:
    logged = await _appended(log, conversation, held)
    await raw_collection.update_one(
        {"conversation_id": conversation}, {"$set": {"runner": {"epoch": 2, "alive_key": "k"}}}
    )
    repository = LogAmendRepository()

    assert not await repository.stage_log_amend(
        conversation, user_id=UID, epoch=1, amended=_edited(logged, "stale")
    )
    assert not await repository.stage_log_amend(
        conversation, user_id="someone-else", epoch=2, amended=_edited(logged, "foreign")
    )
    assert held.spawned == []
    assert await repository.stage_log_amend(
        conversation, user_id=UID, epoch=2, amended=_edited(logged, "edited")
    )
    await held.run_all()

    stored = await _flushed(raw_collection, entries_collection, conversation)
    assert (stored["user_id"], stored["text"], stored["revision"]) == (UID, "edited", 1)


async def test_an_amend_is_staged_once_per_revision_and_flushed_for_its_user(
    log: MongoConversationLog,
    conversation: str,
    raw_collection: Any,
    held: HeldFlushes,
    entries_collection: Any,
) -> None:
    logged = await _appended(log, conversation, held)
    repository = LogAmendRepository()
    before = await raw_collection.find_one({"conversation_id": conversation})

    with patch.object(websocket_manager, "announce") as announce:
        announce.side_effect = lambda *_args: _noop()
        assert await repository.stage_unfenced_amend(
            conversation, user_id=UID, amended=_edited(logged, "edited"), after_revision=0
        )
        assert not await repository.stage_unfenced_amend(
            conversation, user_id=UID, amended=_edited(logged, "late"), after_revision=0
        )
        await held.run_all()

    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after.get("updatedAt") == before.get("updatedAt")
    announce.assert_not_called()
    stored = await _flushed(raw_collection, entries_collection, conversation)
    assert (stored["user_id"], stored["text"], stored["revision"]) == (UID, "edited", 1)


async def test_an_unfenced_amend_follows_a_staged_one_at_the_revision_it_read(
    log: MongoConversationLog,
    conversation: str,
    raw_collection: Any,
    held: HeldFlushes,
    entries_collection: Any,
) -> None:
    logged = await _appended(log, conversation, held)
    repository = LogAmendRepository()
    assert await repository.stage_unfenced_amend(
        conversation, user_id=UID, amended=_edited(logged, "first"), after_revision=0
    )

    assert await repository.stage_unfenced_amend(
        conversation, user_id=UID, amended=_edited(logged, "second", 2), after_revision=1
    )
    await held.run_all()

    stored = await _flushed(raw_collection, entries_collection, conversation)
    assert (stored["text"], stored["revision"]) == ("second", 2)


async def test_an_unfenced_amend_of_another_users_conversation_does_not_land(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    logged = await _appended(log, conversation, held)

    assert not await LogAmendRepository().stage_unfenced_amend(
        conversation, user_id="someone-else", amended=_edited(logged, "x"), after_revision=0
    )
    assert held.spawned == []


async def test_a_synced_amend_advances_the_clock_and_announces_its_row(
    log: MongoConversationLog, conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    logged = await _appended(log, conversation, held)
    before = await raw_collection.find_one({"conversation_id": conversation})

    with patch.object(websocket_manager, "announce") as announce:
        announce.side_effect = lambda *_args: _noop()
        assert await LogAmendRepository().stage_unfenced_amend(
            conversation,
            user_id=UID,
            amended=_edited(logged, "edited"),
            after_revision=0,
            advances_sync=True,
        )
        await held.run_all()

    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after["updatedAt"] != before.get("updatedAt")
    assert announce.call_args.args[0] == UID
    assert announce.call_args.args[1]["conversation_id"] == conversation


async def test_a_pin_bumps_the_revision_once_and_a_repeat_pin_is_a_no_op(
    log: MongoConversationLog, conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    await _appended(log, conversation, held)
    repository = LogAmendRepository()
    before = await raw_collection.find_one({"conversation_id": conversation})

    assert await repository.set_pinned(conversation, user_id=UID, message_id="u1", pinned=True)
    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after["updatedAt"] != before.get("updatedAt")
    with patch.object(repository, "stage_unfenced_amend") as amend:
        assert await repository.set_pinned(conversation, user_id=UID, message_id="u1", pinned=True)
    amend.assert_not_called()

    (pinned,) = await repository.read_log(conversation, user_id=UID, ids=["u1"]) or []
    assert isinstance(pinned.entry, UserMessage)
    assert (pinned.entry.pinned, pinned.entry.revision) == (True, 1)


async def test_an_unpin_clears_the_pin_at_the_next_revision(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _appended(log, conversation, held)
    repository = LogAmendRepository()
    assert await repository.set_pinned(conversation, user_id=UID, message_id="u1", pinned=True)

    assert await repository.set_pinned(conversation, user_id=UID, message_id="u1", pinned=False)

    (unpinned,) = await repository.read_log(conversation, user_id=UID, ids=["u1"]) or []
    assert isinstance(unpinned.entry, UserMessage)
    assert (unpinned.entry.pinned, unpinned.entry.revision) == (False, 2)


async def test_a_reply_is_pinned_by_its_reply_id(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await log.append(conversation, UID, opened("open-1", reply_id="r1"))
    await held.run_all()
    repository = LogAmendRepository()

    assert await repository.set_pinned(conversation, user_id=UID, message_id="r1", pinned=True)

    (reply,) = await repository.read_log(conversation, user_id=UID, reply_ids=["r1"]) or []
    assert isinstance(reply.entry, Reply)
    assert (reply.entry.pinned, reply.entry.revision) == (True, 1)


async def test_nothing_to_pin_is_false_for_a_missing_id_a_notice_or_a_missing_conversation(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await log.append(conversation, UID, notice("n1"))
    await held.run_all()
    repository = LogAmendRepository()

    assert not await repository.set_pinned(
        conversation, user_id=UID, message_id="nope", pinned=True
    )
    assert not await repository.set_pinned(conversation, user_id=UID, message_id="n1", pinned=True)
    assert not await repository.set_pinned("c-missing", user_id=UID, message_id="n1", pinned=True)


async def test_a_pin_that_loses_every_write_says_where(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _appended(log, conversation, held)
    repository = LogAmendRepository()

    with (
        patch.object(repository, "stage_unfenced_amend", AsyncMock(return_value=False)) as amend,
        pytest.raises(ConversationStoreError) as raised,
    ):
        await repository.set_pinned(conversation, user_id=UID, message_id="u1", pinned=True)

    assert amend.await_count == CONVERSATION_APPEND_MAX_ATTEMPTS
    assert raised.value.message == (
        f"pinning in conversation {conversation} lost every conditional write"
    )
    assert raised.value.meta == {"conversation_id": conversation, "entry_id": "u1"}
