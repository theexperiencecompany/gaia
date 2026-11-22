"""LogAppendRepository on real Mongo: the head an append reads, and what its conditional commit leaves on the row."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversation_log_append import LogAppendRepository, LogHead
from app.models.conversation_log_models import (
    SYNCED_KINDS,
    CommsPhase,
    Entry,
    IntegrationNeeded,
    LoggedEntry,
    Rejected,
)
from app.services.conversation.reducer import reduce
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import notice, user
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


async def _read(conversation: str, entry_id: str | None = None) -> LogHead:
    read = await LogAppendRepository().read_log_head(conversation, user_id=UID, entry_id=entry_id)
    assert read is not None
    return read


async def _commit(
    conversation: str,
    entry: Entry,
    *,
    unread: bool = False,
    epoch: int | None = None,
    flush: bool = True,
    read: LogHead | None = None,
) -> bool:
    head = read or await _read(conversation)
    logged = LoggedEntry(seq=head.log_head + 1, at=datetime.now(UTC), entry=entry)
    result = reduce(head.state, logged)
    assert not isinstance(result, Rejected)
    return await LogAppendRepository().commit_log_entry(
        head, logged, result.state, epoch=epoch, unread=unread, flush=flush
    )


async def _noop() -> None:
    return None


async def test_a_missing_or_foreign_conversation_has_no_head(conversation: str) -> None:
    repository = LogAppendRepository()

    assert await repository.read_log_head("c-missing", user_id=UID) is None
    assert await repository.read_log_head(conversation, user_id="someone-else") is None


async def test_a_fresh_head_reads_empty_with_no_state_holder_or_outbox(conversation: str) -> None:
    head = await _read(conversation)

    assert (head.conversation_id, head.user_id) == (conversation, UID)
    assert (head.log_head, head.holder, head.runner_epoch) == (0, None, 0)
    assert head.stored_comms is None
    assert head.unflushed == ()
    assert head.known == {}


async def test_the_head_after_commits_names_its_seq_state_outbox_and_the_asked_entry(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    assert await _commit(conversation, user("u1"))
    assert await _commit(conversation, user("u2"))
    await raw_collection.update_one(
        {"conversation_id": conversation},
        {"$set": {"runner": {"epoch": 3, "alive_key": "k"}, "runner_epoch": 3}},
    )

    staged = await _read(conversation)
    await held.run_all()
    head = await _read(conversation, entry_id="u1")

    assert sorted(stored.model_dump()["id"] for stored in staged.unflushed) == ["u1", "u2"]
    assert staged.known == {"u1": 1, "u2": 2}
    assert head.log_head == 2
    assert head.state.head == 2
    assert head.state.unsettled_waking == (1, 2)
    assert head.stored_comms is CommsPhase.IDLE
    assert (head.holder, head.runner_epoch) == (3, 3)
    assert head.unflushed == ()
    assert head.known == {"u1": 1}
    assert (await _read(conversation)).known == {}


async def test_a_commit_against_a_moved_head_writes_nothing(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    stale = await _read(conversation)
    assert await _commit(conversation, user("u1"))

    assert not await _commit(conversation, user("u2"), read=stale)

    head = await raw_collection.find_one({"conversation_id": conversation})
    assert head["log_head"] == 1
    assert list(head["outbox"]) == ["1"]
    assert [operation for operation, _ in held.spawned].count("conversation_flush") == 1


async def test_a_fenced_commit_lands_only_for_the_epoch_holding_the_step(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    await raw_collection.update_one(
        {"conversation_id": conversation},
        {"$set": {"runner": {"epoch": 2, "alive_key": "k"}, "runner_epoch": 2}},
    )

    assert not await _commit(conversation, notice("n1"), epoch=1)
    assert await _commit(conversation, notice("n1"), epoch=2)

    assert (await _read(conversation)).log_head == 1


async def test_a_commit_read_before_the_comms_phase_changed_does_not_land(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    assert await _commit(conversation, user("u1"))
    read = await _read(conversation)
    await raw_collection.update_one(
        {"conversation_id": conversation}, {"$set": {"state.comms": CommsPhase.ANSWERING.value}}
    )

    assert not await _commit(conversation, user("u2"), read=read)

    assert (await _read(conversation)).stored_comms is CommsPhase.ANSWERING


async def test_a_commit_on_a_head_with_no_state_does_not_land_once_state_appears(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    read = await _read(conversation)
    await raw_collection.update_one(
        {"conversation_id": conversation}, {"$set": {"state.comms": CommsPhase.IDLE.value}}
    )

    assert not await _commit(conversation, user("u1"), read=read)


async def test_an_unread_commit_marks_the_row_and_advances_its_sync_clock(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    need = IntegrationNeeded(id="n1", integration_id="gmail", integration_name="Gmail")
    assert need.kind not in SYNCED_KINDS
    before = await raw_collection.find_one({"conversation_id": conversation})

    assert await _commit(conversation, need, unread=True)

    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after["is_unread"] is True
    assert after["updatedAt"] != before.get("updatedAt")
    assert [operation for operation, _ in held.spawned] == [
        "conversation_list_push",
        "conversation_flush",
    ]


async def test_a_synced_entry_advances_the_sync_clock_without_marking_the_row_unread(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    message = user("u1")
    assert message.kind in SYNCED_KINDS
    before = await raw_collection.find_one({"conversation_id": conversation})

    assert await _commit(conversation, message)

    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after.get("is_unread") == before.get("is_unread")
    assert after["updatedAt"] != before.get("updatedAt")
    assert [operation for operation, _ in held.spawned] == [
        "conversation_list_push",
        "conversation_flush",
    ]


async def test_a_quiet_commit_of_an_unsynced_entry_leaves_the_row_as_it_was(
    conversation: str, raw_collection: Any, held: HeldFlushes
) -> None:
    need = IntegrationNeeded(id="n1", integration_id="gmail", integration_name="Gmail")
    before = await raw_collection.find_one({"conversation_id": conversation})

    assert await _commit(conversation, need)

    after = await raw_collection.find_one({"conversation_id": conversation})
    assert after.get("is_unread") == before.get("is_unread")
    assert after.get("updatedAt") == before.get("updatedAt")
    assert [operation for operation, _ in held.spawned] == ["conversation_flush"]


async def test_a_commit_by_default_leaves_the_row_read_and_flushes_its_entry(
    conversation: str, raw_collection: Any, held: HeldFlushes, entries_collection: Any
) -> None:
    head = await _read(conversation)
    logged = LoggedEntry(seq=1, at=datetime.now(UTC), entry=notice("n1"))
    result = reduce(head.state, logged)
    assert not isinstance(result, Rejected)

    assert await LogAppendRepository().commit_log_entry(head, logged, result.state, epoch=None)
    await held.run_all()

    row = await raw_collection.find_one({"conversation_id": conversation})
    assert row.get("is_unread") is not True
    stored = await entries_collection.find_one({"conversation_id": conversation, "seq": 1})
    assert stored is not None


async def test_an_unflushed_commit_is_carried_by_the_next_commits_flush(
    conversation: str, held: HeldFlushes, entries_collection: Any
) -> None:
    assert await _commit(conversation, notice("n1"), flush=False)
    assert "conversation_flush" not in [operation for operation, _ in held.spawned]

    assert await _commit(conversation, notice("n2"))
    await held.run_all()

    stored = await entries_collection.find({"conversation_id": conversation}).to_list(None)
    assert sorted((row["seq"], row["id"], row["user_id"]) for row in stored) == [
        (1, "n1", UID),
        (2, "n2", UID),
    ]


async def test_a_commit_announces_and_flushes_for_its_own_user(
    conversation: str, held: HeldFlushes, entries_collection: Any
) -> None:
    with patch.object(websocket_manager, "announce") as announce:
        announce.side_effect = lambda *_args: _noop()
        await _commit(conversation, user("u1"), unread=True)
        await held.run_all()

    announce.assert_called_once()
    assert announce.call_args.args[0] == UID
    assert announce.call_args.args[1]["conversation_id"] == conversation
    stored = await entries_collection.find_one({"conversation_id": conversation})
    assert (stored["user_id"], stored["seq"]) == (UID, 1)
