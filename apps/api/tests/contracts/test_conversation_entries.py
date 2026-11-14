"""The conversation-entries append protocol against real Mongo: one seq allocator, an outbox, a union read."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call
import uuid

from pymongo.errors import ServerSelectionTimeoutError
import pytest

from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_entries import EMBEDDED_FINGERPRINT, EntryWindow
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSyncItem, MessageModel, ToolDataEntry
from app.models.conversation_models import (
    ConversationDescriptionHit,
    ConversationDocument,
)
from app.utils.errors import (
    ConversationNotFoundError,
    ConversationStoreError,
    UnmigratedConversationError,
)
from shared.py.wide_events import log
from tests.contracts.conftest import HeldFlushes

# Every test here writes entries, so each needs the collection with its unique indexes.
pytestmark = pytest.mark.usefixtures("entries_collection")


@pytest.fixture
def repo(raw_collection: Any) -> ConversationRepository:
    return ConversationRepository()


@pytest.fixture
async def conversation(repo: ConversationRepository) -> ConversationDocument:
    doc = ConversationDocument.model_validate(
        {
            "user_id": f"u-{uuid.uuid4().hex}",
            "conversation_id": f"c-{uuid.uuid4().hex}",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    )
    await repo.create(doc)
    return doc


def _message(message_id: str, text: str = "hi") -> MessageModel:
    return MessageModel(type="user", response=text, message_id=message_id)


async def _ids(repo: ConversationRepository, doc: ConversationDocument) -> list[tuple[int, str]]:
    entries = await repo._read_entries(doc.conversation_id, user_id=doc.user_id)
    return [(entry.seq, entry.message_id or "") for entry in entries]


async def _outbox(raw_collection: Any, doc: ConversationDocument) -> dict[str, Any]:
    head = await raw_collection.find_one({"conversation_id": doc.conversation_id})
    assert head is not None
    return dict(head.get("outbox") or {})


async def test_concurrent_appends_take_every_seq_once_in_order(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    async def producer(task: int) -> list[int]:
        seqs: list[int] = []
        for n in range(5):
            seqs.extend(
                await repo.append(
                    conversation.conversation_id,
                    user_id=conversation.user_id,
                    entries=[_message(f"t{task}-{n}")],
                )
            )
        return seqs

    results = await asyncio.gather(*(producer(task) for task in range(10)))
    await held.run_all()

    assert sorted(seq for seqs in results for seq in seqs) == list(range(1, 51))
    read = await _ids(repo, conversation)
    assert [seq for seq, _ in read] == list(range(1, 51))
    assert len({message_id for _, message_id in read}) == 50


async def test_an_entry_is_read_the_moment_append_returns(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    [seq] = await repo.append(
        conversation.conversation_id, user_id=conversation.user_id, entries=[_message("m1")]
    )

    assert held.held, "the flush must not have run yet"
    assert held.spawned == [
        ("conversation_flush", {"conversation_id": conversation.conversation_id})
    ]
    assert await _ids(repo, conversation) == [(seq, "m1")]


async def test_a_flush_that_never_ran_is_finished_by_the_next_append_or_flush_outbox(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    await repo.append(
        conversation.conversation_id, user_id=conversation.user_id, entries=[_message("m1")]
    )
    held.drop_all()
    before = await _ids(repo, conversation)
    assert before == [(1, "m1")]
    assert list(await _outbox(raw_collection, conversation)) == ["1"]

    await repo.append(
        conversation.conversation_id, user_id=conversation.user_id, entries=[_message("m2")]
    )
    await held.run_all()

    assert await _outbox(raw_collection, conversation) == {}
    assert await entries_collection.count_documents({}) == 2
    assert await _ids(repo, conversation) == [(1, "m1"), (2, "m2")]

    await repo.append(
        conversation.conversation_id, user_id=conversation.user_id, entries=[_message("m3")]
    )
    held.drop_all()
    during = await _ids(repo, conversation)
    await repo.flush_outbox(conversation.conversation_id, user_id=conversation.user_id)
    assert await _outbox(raw_collection, conversation) == {}
    assert during == await _ids(repo, conversation) == [(1, "m1"), (2, "m2"), (3, "m3")]


async def test_the_same_id_appended_twice_is_one_entry_with_one_seq(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    first = await repo.append(cid, user_id=uid, entries=[_message("same")])
    again = await repo.append(cid, user_id=uid, entries=[_message("same")])
    assert len(held.held) == 2, "a repeat that sees a pending outbox still flushes it"
    await held.run_all()
    after_flush = await repo.append(cid, user_id=uid, entries=[_message("same")])
    assert held.held == [], "a repeat with nothing pending writes and flushes nothing"
    racing = await asyncio.gather(
        repo.append(cid, user_id=uid, entries=[_message("twin")]),
        repo.append(cid, user_id=uid, entries=[_message("twin")]),
    )
    await held.run_all()

    assert first == again == after_flush == [1]
    assert racing[0] == racing[1] == [2]
    assert await _ids(repo, conversation) == [(1, "same"), (2, "twin")]


async def test_a_batch_with_one_known_id_appends_only_the_new_ones(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("a"), _message("known")])
    await held.run_all()

    seqs = await repo.append(
        cid, user_id=uid, entries=[_message("b"), _message("known"), _message("c")]
    )
    await held.run_all()

    assert seqs == [3, 2, 4]
    assert await _ids(repo, conversation) == [(1, "a"), (2, "known"), (3, "b"), (4, "c")]


async def test_an_update_to_an_entry_still_in_the_outbox_is_applied(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1", "draft")])
    held.drop_all()

    assert await repo.set_message_response(cid, user_id=uid, message_id="m1", response="final")

    assert await _outbox(raw_collection, conversation) == {}
    saved = await repo.get_message(cid, "m1", user_id=uid)
    assert saved is not None and saved.response == "final"
    assert not await repo.set_message_response(cid, user_id=uid, message_id="nope", response="x")


async def test_settling_an_approval_reaches_every_message_holding_it_flushed_or_not(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    frame: ToolDataEntry = {
        "tool_name": "approval_request",
        "data": {"approval_id": "a1", "status": "pending"},
    }

    def card(message_id: str) -> MessageModel:
        return MessageModel(type="bot", response="", message_id=message_id, tool_data=[frame])

    await repo.append(cid, user_id=uid, entries=[card("flushed")])
    await held.run_all()
    await repo.append(cid, user_id=uid, entries=[card("pending")])
    held.drop_all()

    assert await repo.set_message_approval_status(
        cid, user_id=uid, approval_id="a1", status="approved"
    )

    for message_id in ("flushed", "pending"):
        saved = await repo.get_message(cid, message_id, user_id=uid)
        assert saved is not None and saved.tool_data is not None
        assert [entry["data"]["status"] for entry in saved.tool_data] == ["approved"], message_id


async def test_a_read_between_insert_and_unset_sees_the_entry_once(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1")])
    held.drop_all()
    committed_only = await _ids(repo, conversation)

    pending = (await _outbox(raw_collection, conversation))["1"]
    await entries_collection.insert_one(dict(pending))
    inserted_not_unset = await _ids(repo, conversation)

    await repo.flush_outbox(cid, user_id=uid)
    flushed = await _ids(repo, conversation)

    assert committed_only == inserted_not_unset == flushed == [(1, "m1")]


async def test_reads_racing_flushes_never_miss_or_duplicate(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    expected: list[tuple[int, str]] = []
    for n in range(1, 31):
        await repo.append(cid, user_id=uid, entries=[_message(f"m{n}")])
        expected.append((n, f"m{n}"))
        reads = await asyncio.gather(
            _ids(repo, conversation),
            held.run_all(),
            _ids(repo, conversation),
            _ids(repo, conversation),
        )
        assert reads[0] == reads[2] == reads[3] == expected


async def test_the_last_n_messages_take_the_highest_seqs_across_both_stores(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message(f"m{n}") for n in range(1, 5)])
    await held.run_all()
    await repo.append(cid, user_id=uid, entries=[_message("m5"), _message("m6")])
    held.drop_all()

    recent = await repo.list_recent_messages(cid, user_id=uid, limit=3)
    newest = await repo._read_entries(
        cid, user_id=uid, window=EntryWindow(limit=2, newest_first=True)
    )
    window = await repo._read_entries(
        cid, user_id=uid, window=EntryWindow(after_seq=2, before_seq=5)
    )

    assert [m.message_id for m in recent] == ["m4", "m5", "m6"]
    assert [e.seq for e in newest] == [6, 5]
    assert [e.seq for e in window] == [3, 4]
    assert await repo.list_recent_messages("missing", user_id=uid, limit=3) == []


async def test_append_to_a_missing_conversation_raises_and_writes_nothing(
    repo: ConversationRepository,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    missing = f"c-{uuid.uuid4().hex}"
    with pytest.raises(ConversationNotFoundError) as raised:
        await repo.append(missing, user_id="u", entries=[_message("m1")])

    assert raised.value.message == f"conversation {missing} does not exist for this user"
    assert raised.value.meta == {"conversation_id": missing}

    assert held.held == []
    assert await raw_collection.count_documents({}) == 0
    assert await entries_collection.count_documents({}) == 0


async def test_an_unmigrated_conversation_is_refused_by_name(
    repo: ConversationRepository, raw_collection: Any, held: HeldFlushes
) -> None:
    await raw_collection.insert_one(
        {
            "conversation_id": "legacy",
            "user_id": "u",
            "createdAt": datetime.now(UTC).isoformat(),
            "messages": [{"type": "user", "response": "old", "message_id": "o1"}],
        }
    )

    with pytest.raises(UnmigratedConversationError, match="migrate_conversation_entries"):
        await repo._read_entries("legacy", user_id="u")
    with pytest.raises(UnmigratedConversationError, match="migrate_conversation_entries"):
        await repo.get("legacy", user_id="u")
    with pytest.raises(UnmigratedConversationError):
        await repo.append("legacy", user_id="u", entries=[_message("m1")])
    assert held.held == []


async def test_deleting_conversations_deletes_their_entries(
    repo: ConversationRepository, held: HeldFlushes, entries_collection: Any
) -> None:
    async def seeded(user_id: str, **fields: object) -> str:
        doc = ConversationDocument.model_validate(
            {
                "user_id": user_id,
                "conversation_id": f"c-{uuid.uuid4().hex}",
                "createdAt": datetime.now(UTC).isoformat(),
                **fields,
            }
        )
        await repo.create(doc)
        await repo.append(doc.conversation_id, user_id=user_id, entries=[_message("m")])
        await held.run_all()
        return doc.conversation_id

    one = await seeded("u1")
    await seeded("u1", is_onboarding_demo=True)
    await seeded("u2")
    await seeded("u3")
    await seeded("u3", todo_id="todo-1")
    assert await entries_collection.count_documents({}) == 5

    assert await repo.delete(one, user_id="u1")
    assert await repo.delete_onboarding_demos("u1") == 1
    assert await entries_collection.count_documents({"user_id": "u1"}) == 0
    await repo.delete_all_for_user("u2")
    assert await entries_collection.count_documents({"user_id": "u2"}) == 0
    await repo.delete_all_chats_for_user("u3")
    assert await entries_collection.count_documents({"user_id": "u3"}) == 1
    await repo.delete_for_todos("u3", ["todo-1"])
    assert await entries_collection.count_documents({}) == 0


async def _chat(repo: ConversationRepository, user_id: str, **fields: object) -> str:
    doc = ConversationDocument.model_validate(
        {
            "user_id": user_id,
            "conversation_id": f"c-{uuid.uuid4().hex}",
            "createdAt": datetime.now(UTC).isoformat(),
            **fields,
        }
    )
    await repo.create(doc)
    return doc.conversation_id


async def test_cross_conversation_reads_see_flushed_and_outbox_entries(
    repo: ConversationRepository, held: HeldFlushes
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    flushed = await _chat(repo, uid)
    pending = await _chat(repo, uid)
    workflow = await _chat(repo, uid, is_system_generated=True)
    pinned_bot = MessageModel(type="bot", response="weekly plan", message_id="b1", pinned=True)
    await repo.append(flushed, user_id=uid, entries=[pinned_bot])
    await held.run_all()
    await repo.append(workflow, user_id=uid, entries=[_message("w1", "weekly prompt")])
    await held.run_all()
    assert await repo.has_sent_message(uid) is False

    pinned_reply = MessageModel(type="bot", response="weekly recap", message_id="b2", pinned=True)
    await repo.append(pending, user_id=uid, entries=[_message("u1", "hello"), pinned_reply])
    held.drop_all()

    assert await repo.has_sent_message(uid) is True
    assert await repo.find_owner_of_message(uid, "b2") == pending
    assert await repo.find_owner_of_message(uid, "u1", message_type="user") == pending
    assert await repo.find_owner_of_message(uid, "u1") is None
    pins = await repo.list_pinned_messages(uid)
    assert {(h.conversation_id, h.message.message_id) for h in pins} == {
        (flushed, "b1"),
        (pending, "b2"),
    }
    found = await repo.search(uid, pattern="weekly")
    assert {(h.conversation_id, h.message.message_id) for h in found.messages} == {
        (flushed, "b1"),
        (pending, "b2"),
        (workflow, "w1"),
    }


async def test_a_bounded_cross_conversation_read_takes_at_most_its_limit_from_the_collection(
    repo: ConversationRepository, held: _HeldFlushes
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    cid = await _chat(repo, uid)
    await repo.append(cid, user_id=uid, entries=[_message("u1", "a"), _message("u2", "b")])
    await held.run_all()

    assert len(await repo._find_entries(uid, {"type": "user"})) == 2
    assert len(await repo._find_entries(uid, {"type": "user"}, limit=1)) == 1


async def test_search_skips_a_todos_chat_and_an_unmigrated_chat_never_blocks_the_others(
    repo: ConversationRepository,
    held: HeldFlushes,
    raw_collection: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    todo_chat = await _chat(repo, uid, todo_id="todo-1", description="needle todo")
    described = await _chat(repo, uid, description="needle notes")
    await repo.append(todo_chat, user_id=uid, entries=[_message("t1", "needle")])
    held.drop_all()
    found = await repo.search(uid, pattern="needle")
    assert found.messages == []
    assert found.conversations == [
        ConversationDescriptionHit(conversation_id=described, description="needle notes")
    ]

    await raw_collection.insert_one(
        {
            "conversation_id": "old",
            "user_id": uid,
            "messages": [{"type": "user", "response": "needle", "message_id": "o1"}],
        }
    )
    await raw_collection.insert_one(
        {
            "conversation_id": "elsewhere",
            "user_id": f"other-{uid}",
            "messages": [{"type": "user", "response": "needle", "message_id": "e1"}],
        }
    )
    await repo.append(described, user_id=uid, entries=[_message("d1", "needle")])
    await held.run_all()
    warned = Mock()
    monkeypatch.setattr(log, "warning", warned)
    found = await repo.search(uid, pattern="needle")
    assert warned.call_args_list == [
        call(
            "[conversations] cross-conversation read left out unmigrated conversations",
            user_id=uid,
            conversation_ids=["old"],
        )
    ]
    assert [(h.conversation_id, h.message.message_id) for h in found.messages] == [
        (described, "d1")
    ]
    assert await repo.has_sent_message(uid) is True


_REFUSAL = (
    "has messages the entries migration has not copied: run python -m "
    "app.scripts.migrate_conversation_entries --apply"
)


async def test_a_migrated_head_reads_until_the_old_build_writes_its_array_again(
    repo: ConversationRepository, raw_collection: Any, entries_collection: Any
) -> None:
    old = {"type": "user", "response": "old", "message_id": "o1"}
    await raw_collection.insert_one(
        {
            "conversation_id": "migrated",
            "user_id": "u",
            "createdAt": datetime.now(UTC).isoformat(),
            "messages": [old],
            "log_head": 1,
        }
    )
    # Marked the way the migration marks a head it copied: the array's fingerprint at copy time.
    await raw_collection.update_one(
        {"conversation_id": "migrated"}, [{"$set": {"migrated_fingerprint": EMBEDDED_FINGERPRINT}}]
    )
    await entries_collection.insert_one(
        {
            "conversation_id": "migrated",
            "user_id": "u",
            "seq": 1,
            "id": "o1",
            "type": "user",
            "response": "old",
            "at": datetime.now(UTC),
        }
    )
    doc = await repo.get("migrated", user_id="u")
    assert doc is not None and [m.message_id for m in doc.messages] == ["o1"]

    await raw_collection.update_one(
        {"conversation_id": "migrated"}, {"$push": {"messages": {**old, "message_id": "o2"}}}
    )

    with pytest.raises(UnmigratedConversationError) as refused:
        await repo.get("migrated", user_id="u")
    assert refused.value.message == f"conversation migrated {_REFUSAL}"
    assert refused.value.why == "its messages still live only in the embedded messages array"


async def test_a_head_written_before_log_head_existed_starts_its_log_at_one(
    repo: ConversationRepository, raw_collection: Any, held: HeldFlushes
) -> None:
    await raw_collection.insert_one(
        {"conversation_id": "early", "user_id": "u", "createdAt": datetime.now(UTC).isoformat()}
    )

    assert await repo.append("early", user_id="u", entries=[_message("m1")]) == [1]
    assert await repo.append("early", user_id="u", entries=[_message("m2")]) == [2]
    head = await raw_collection.find_one({"conversation_id": "early"})
    assert head is not None and head["log_head"] == 2


async def test_a_flush_never_drops_an_entry_whose_seq_another_entry_holds(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1")])
    held.drop_all()
    await entries_collection.insert_one(
        {
            "conversation_id": cid,
            "user_id": uid,
            "seq": 1,
            "id": "intruder",
            "at": datetime.now(UTC),
        }
    )

    with pytest.raises(ConversationStoreError) as conflict:
        await repo.flush_outbox(cid, user_id=uid)

    assert conflict.value.message == "an outbox entry conflicts with a stored entry"
    assert "E11000" in conflict.value.why
    assert list(await _outbox(raw_collection, conversation)) == ["1"]


async def test_an_entry_without_a_commit_time_is_refused_as_corrupt(
    repo: ConversationRepository, conversation: ConversationDocument, entries_collection: Any
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await entries_collection.insert_one(
        {"conversation_id": cid, "user_id": uid, "seq": 1, "id": "m1", "pinned": True}
    )

    with pytest.raises(ConversationStoreError) as corrupt:
        await repo.list_pinned_messages(uid)

    assert corrupt.value.message == "a stored conversation entry has no commit time"
    assert corrupt.value.meta == {"conversation_id": cid, "seq": "1"}


async def test_a_driver_failure_surfaces_as_the_stores_error_naming_the_operation(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = ServerSelectionTimeoutError("no primary")

    def down(*_: object, **__: object) -> None:
        raise failure

    monkeypatch.setattr(repo, "_raw_collection", lambda: SimpleNamespace(aggregate=down))

    with pytest.raises(ConversationStoreError) as raised:
        await repo.get(conversation.conversation_id, user_id=conversation.user_id)

    assert raised.value.message == "conversation store head read failed"
    assert raised.value.why == "no primary"
    assert raised.value.meta == {"error_type": "ServerSelectionTimeoutError"}
    assert raised.value.__cause__ is failure


async def test_an_entry_without_its_id_is_refused_before_anything_is_written(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    with pytest.raises(ValueError, match="^an appended entry carries its producer-minted id$"):
        await repo.append(
            conversation.conversation_id,
            user_id=conversation.user_id,
            entries=[_message("m1"), MessageModel(type="user", response="no id")],
        )

    assert await _ids(repo, conversation) == []
    assert held.held == []


async def test_one_id_twice_in_a_batch_is_one_entry_holding_its_first_copy(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id

    seqs = await repo.append(
        cid, user_id=uid, entries=[_message("d", "first"), _message("d", "second")]
    )

    assert seqs == [1, 1]
    saved = await repo.get_message(cid, "d", user_id=uid)
    assert saved is not None and saved.response == "first"
    assert await _ids(repo, conversation) == [(1, "d")]


async def test_an_append_that_loses_every_conditional_write_raises_and_commits_nothing(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    attempts: list[int] = []

    async def lost(*_: object) -> bool:
        attempts.append(1)
        return False

    monkeypatch.setattr(conversations_module, "CONVERSATION_APPEND_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(repo, "_commit", lost)

    with pytest.raises(ConversationStoreError) as raised:
        await repo.append(cid, user_id=uid, entries=[_message("m1")])

    assert raised.value.message == f"append to conversation {cid} lost every conditional write"
    assert raised.value.why == "the head moved under each of 3 attempts"
    assert raised.value.meta == {"conversation_id": cid}
    assert len(attempts) == 3
    assert await _ids(repo, conversation) == []


async def test_parking_cards_that_loses_every_conditional_write_raises(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id

    async def lost(*_: object, **__: object) -> int:
        return 0

    monkeypatch.setattr(conversations_module, "CONVERSATION_APPEND_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(repo, "_apply_pipeline_update_unfetched", lost)

    with pytest.raises(ConversationStoreError) as raised:
        await repo.park_folded_cards(
            cid, user_id=uid, message_id="m1", entries=[{"tool_name": "x"}]
        )

    assert (
        raised.value.message == f"parking cards on conversation {cid} lost every conditional write"
    )
    assert raised.value.meta == {"conversation_id": cid}


async def test_a_flush_of_a_conversation_deleted_under_it_takes_back_what_it_inserted(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1")])
    held.drop_all()
    other = await _chat(repo, uid)
    await repo.append(other, user_id=uid, entries=[_message("kept")])
    await held.run_all()
    insert = repo._insert_entries

    async def insert_then_delete(entries: Any) -> None:
        await insert(entries)
        await raw_collection.delete_one({"conversation_id": cid})

    monkeypatch.setattr(repo, "_insert_entries", insert_then_delete)

    await repo.flush_outbox(cid, user_id=uid)

    assert await entries_collection.count_documents({"conversation_id": cid}) == 0
    assert await entries_collection.count_documents({"conversation_id": other}) == 1


async def test_a_repeat_append_finishes_the_flush_the_first_append_never_ran(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1")])
    held.drop_all()
    held.spawned.clear()

    assert await repo.append(cid, user_id=uid, entries=[_message("m1")]) == [1]
    assert held.spawned == [("conversation_flush", {"conversation_id": cid})]
    await held.run_all()

    assert await _outbox(raw_collection, conversation) == {}
    assert await entries_collection.count_documents({"conversation_id": cid}) == 1


async def test_two_users_conversations_under_one_id_keep_their_own_entries(
    repo: ConversationRepository, held: HeldFlushes
) -> None:
    shared = f"c-{uuid.uuid4().hex}"
    first, second = f"u-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    for user_id in (first, second):
        await _chat(repo, user_id, conversation_id=shared)

    await repo.append(shared, user_id=second, entries=[_message("m1")])
    await held.run_all()

    theirs = await repo.get(shared, user_id=second)
    other = await repo.get(shared, user_id=first)
    assert theirs is not None and [m.message_id for m in theirs.messages] == ["m1"]
    assert other is not None and other.messages == []


async def test_a_created_conversation_head_holds_no_messages_and_an_empty_log(
    repo: ConversationRepository, raw_collection: Any
) -> None:
    doc = ConversationDocument.model_validate(
        {
            "user_id": f"u-{uuid.uuid4().hex}",
            "conversation_id": f"c-{uuid.uuid4().hex}",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    )

    await repo.create(doc)

    head = await raw_collection.find_one({"conversation_id": doc.conversation_id})
    assert head is not None
    assert not {"id", "messages"} & set(head)
    assert head["log_head"] == 0


async def test_pinning_a_stored_message_bumps_updated_at_and_leaves_the_outbox_to_its_flush(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("m1")])
    await held.run_all()
    await repo.append(cid, user_id=uid, entries=[_message("m2")])
    held.drop_all()
    stale = datetime(2020, 1, 1, tzinfo=UTC)
    await raw_collection.update_one({"conversation_id": cid}, {"$set": {"updatedAt": stale}})

    assert await repo.set_message_pinned(cid, user_id=uid, message_id="m1", pinned=True)

    head = await raw_collection.find_one({"conversation_id": cid})
    assert head is not None and head["updatedAt"].year > stale.year
    assert list(await _outbox(raw_collection, conversation)) == ["2"]
    saved = await repo.get_message(cid, "m1", user_id=uid)
    assert saved is not None and saved.pinned is True


async def test_pinning_an_unknown_message_is_refused_and_leaves_updated_at(
    repo: ConversationRepository, conversation: ConversationDocument, raw_collection: Any
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    stale = datetime(2020, 1, 1, tzinfo=UTC)
    await raw_collection.update_one({"conversation_id": cid}, {"$set": {"updatedAt": stale}})

    assert not await repo.set_message_pinned(cid, user_id=uid, message_id="nope", pinned=True)

    head = await raw_collection.find_one({"conversation_id": cid})
    assert head is not None and head["updatedAt"].year == stale.year


async def test_recent_conversations_are_the_newest_limit_with_their_messages(
    repo: ConversationRepository, held: HeldFlushes
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    await _chat(repo, uid, createdAt="2026-01-01T00:00:00+00:00")
    middle = await _chat(repo, uid, createdAt="2026-01-02T00:00:00+00:00")
    newest = await _chat(repo, uid, createdAt="2026-01-03T00:00:00+00:00")
    await repo.append(newest, user_id=uid, entries=[_message("m1")])
    held.drop_all()

    recent = await repo.recent_for_user(uid, limit=2)

    assert [doc.conversation_id for doc in recent] == [newest, middle]
    assert [m.message_id for m in recent[0].messages] == ["m1"]


async def _orphaned(
    repo: ConversationRepository, held: HeldFlushes, raw_collection: Any, uid: str
) -> str:
    """Leave the state a delete that died between its two writes leaves: entries with no head."""
    cid = await _chat(repo, uid)
    old = MessageModel(type="bot", response="deleted secret", message_id="old-1", pinned=True)
    await repo.append(cid, user_id=uid, entries=[_message("old-0", "deleted secret"), old])
    await held.run_all()
    await raw_collection.delete_one({"conversation_id": cid, "user_id": uid})
    return cid


async def test_a_bot_chat_recreated_after_a_half_finished_delete_starts_clean_and_keeps_saving(
    repo: ConversationRepository, held: HeldFlushes, raw_collection: Any
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    cid = await _orphaned(repo, held, raw_collection, uid)
    doc = ConversationDocument.model_validate(
        {"user_id": uid, "conversation_id": cid, "createdAt": datetime.now(UTC).isoformat()}
    )

    await repo.create(doc)
    await repo.append(cid, user_id=uid, entries=[_message("new-1", "fresh")])
    await repo.append(cid, user_id=uid, entries=[_message("new-2", "fresher")])
    await held.run_all()

    assert await _ids(repo, doc) == [(1, "new-1"), (2, "new-2")]
    assert await _outbox(raw_collection, doc) == {}


async def test_a_deleted_conversations_leftover_entries_never_reach_search_or_pins(
    repo: ConversationRepository, held: HeldFlushes, raw_collection: Any
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    await _orphaned(repo, held, raw_collection, uid)
    live = await _chat(repo, uid)
    await repo.append(live, user_id=uid, entries=[_message("live-1", "kept secret")])
    await held.run_all()

    found = await repo.search(uid, pattern="secret")
    assert [(h.conversation_id, h.message.message_id) for h in found.messages] == [(live, "live-1")]
    assert await repo.list_pinned_messages(uid) == []
    assert await repo.find_owner_of_message(uid, "old-1") is None


async def test_whole_conversation_reads_return_only_the_newest_window(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 3)
    cid, uid = conversation.conversation_id, conversation.user_id
    other = await _chat(repo, uid)
    await repo.append(cid, user_id=uid, entries=[_message(f"m{n}") for n in range(1, 5)])
    await held.run_all()
    await repo.append(cid, user_id=uid, entries=[_message("m5")])
    await repo.append(other, user_id=uid, entries=[_message("o1")])
    held.drop_all()

    doc = await repo.get(cid, user_id=uid)
    assert doc is not None
    assert [m.message_id for m in doc.messages] == ["m3", "m4", "m5"]
    synced = await repo.find_updated_since(
        uid,
        [
            ConversationSyncItem(conversation_id=cid, last_updated=None),
            ConversationSyncItem(conversation_id=other, last_updated=None),
        ],
    )
    windows = {d.conversation_id: [m.message_id for m in d.messages] for d in synced}
    assert windows == {cid: ["m3", "m4", "m5"], other: ["o1"]}
    recent = await repo.recent_for_user(uid, limit=2)
    assert {d.conversation_id: [m.message_id for m in d.messages] for d in recent} == windows


@pytest.mark.parametrize("flushed", [False, True])
async def test_a_retried_append_of_a_known_id_with_other_content_fails_instead_of_reporting_it_saved(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    flushed: bool,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await repo.append(cid, user_id=uid, entries=[_message("r1", "")])
    if flushed:
        await held.run_all()

    assert await repo.append(cid, user_id=uid, entries=[_message("r1", "")]) == [1]
    with pytest.raises(ConversationStoreError) as refused:
        await repo.append(cid, user_id=uid, entries=[_message("r1", "the full reply")])

    assert (refused.value.message, refused.value.why, refused.value.meta) == (
        "entry r1 is already committed with other content",
        "an append is idempotent only for the same message; fill or edit the entry instead",
        {"conversation_id": cid, "entry_id": "r1"},
    )

    kept = await repo.get_message(cid, "r1", user_id=uid)
    assert kept is not None and kept.response == ""


async def test_the_reply_sweep_settles_a_reply_whose_process_died_before_its_flush(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    opened = MessageModel(type="bot", response="", message_id="r1", in_progress=True)
    await repo.append(cid, user_id=uid, entries=[opened])
    # The process dies here: the flush append spawned never runs.
    held.drop_all()
    cutoff = datetime.now(UTC) + timedelta(seconds=1)

    owners = await repo.list_unfinished_reply_owners(opened_before=cutoff)
    assert owners == {(uid, cid)}
    assert (
        await repo.fail_unfinished_replies(opened_before=cutoff, error="interrupted", owners=owners)
        == 1
    )

    settled = await repo.get_message(cid, "r1", user_id=uid)
    assert settled is not None
    assert (settled.in_progress, settled.error) == (None, "interrupted")
