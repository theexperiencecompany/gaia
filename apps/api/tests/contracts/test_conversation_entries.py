"""The conversation-entries append protocol against real Mongo: one seq allocator, an outbox, a union read."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
import uuid

from pymongo.errors import ServerSelectionTimeoutError
import pytest

from app.constants.chat import ConversationSource
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_entries import EntryWindow
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSyncItem
from app.models.conversation_log_models import (
    Entry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
)
from app.models.conversation_models import (
    ConversationDescriptionHit,
    ConversationDocument,
    ConversationEntriesPage,
)
from app.services.conversation import mongo_log as mongo_log_module
from app.services.conversation.mongo_log import MongoConversationLog
from app.utils.errors import (
    ConversationNotFoundError,
    ConversationStoreError,
)
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


def _message(message_id: str, text: str = "hi") -> UserMessage:
    return UserMessage(id=message_id, text=text, surface=ConversationSource.WEB)


def _flushed_at_once(message_id: str) -> UserMessage:
    """Build an imported message: it kicks no step, so its own append spawns its flush."""
    return _message(message_id).model_copy(update={"imported": True})


def _log() -> MongoConversationLog:
    return MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))


def _reply(reply_id: str, text: str) -> Reply:
    """Build a pinned reply still open: its pin and text are searchable before it settles."""
    return Reply(id=f"o-{reply_id}", reply_id=reply_id, attempt_id="a1", text=text, pinned=True)


async def _pin(conversation_id: str, user_id: str, message_id: str) -> bool:
    return await conversation_log_repository.set_pinned(
        conversation_id, user_id=user_id, message_id=message_id, pinned=True
    )


async def _append(conversation_id: str, user_id: str, messages: list[Entry]) -> list[int]:
    """Append each message to the conversation's log; return the seqs they were stored at."""
    return [
        (await _log().append(conversation_id, user_id, message)).logged.seq for message in messages
    ]


async def _read(conversation_id: str, user_id: str, entry_id: str) -> list[Entry]:
    logged = await conversation_log_repository.read_log(
        conversation_id, user_id=user_id, ids=[entry_id]
    )
    assert logged is not None
    return [entry.entry for entry in logged]


async def _ids(repo: ConversationRepository, doc: ConversationDocument) -> list[tuple[int, str]]:
    entries = await _log().read_after(doc.conversation_id, doc.user_id, 0)
    return [(entry.seq, entry.entry.id) for entry in entries]


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
                await _append(
                    conversation.conversation_id, conversation.user_id, [_message(f"t{task}-{n}")]
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
    [seq] = await _append(
        conversation.conversation_id, conversation.user_id, [_flushed_at_once("m1")]
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
    await _append(conversation.conversation_id, conversation.user_id, [_flushed_at_once("m1")])
    held.drop_all()
    before = await _ids(repo, conversation)
    assert before == [(1, "m1")]
    assert list(await _outbox(raw_collection, conversation)) == ["1"]

    await _append(conversation.conversation_id, conversation.user_id, [_flushed_at_once("m2")])
    await held.run_all()

    assert await _outbox(raw_collection, conversation) == {}
    assert await entries_collection.count_documents({}) == 2
    assert await _ids(repo, conversation) == [(1, "m1"), (2, "m2")]

    await _append(conversation.conversation_id, conversation.user_id, [_flushed_at_once("m3")])
    held.drop_all()
    during = await _ids(repo, conversation)
    await repo.flush_outbox(conversation.conversation_id, user_id=conversation.user_id)
    assert await _outbox(raw_collection, conversation) == {}
    assert during == await _ids(repo, conversation) == [(1, "m1"), (2, "m2"), (3, "m3")]


async def test_the_same_id_appended_twice_is_one_entry_with_one_seq(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    first = await _append(cid, uid, [_message("same")])
    again = await _append(cid, uid, [_message("same")])
    await held.run_all()
    after_flush = await _append(cid, uid, [_message("same")])
    assert held.held == [], "a repeat writes and flushes nothing"
    racing = await asyncio.gather(
        _append(cid, uid, [_message("twin")]),
        _append(cid, uid, [_message("twin")]),
    )
    await held.run_all()

    assert first == again == after_flush == [1]
    assert racing[0] == racing[1] == [2]
    assert await _ids(repo, conversation) == [(1, "same"), (2, "twin")]


async def test_a_batch_with_one_known_id_appends_only_the_new_ones(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_message("a"), _message("known")])
    await held.run_all()

    seqs = await _append(cid, uid, [_message("b"), _message("known"), _message("c")])
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
    await _append(cid, uid, [_message("m1", "draft")])
    held.drop_all()

    assert await _pin(cid, uid, "m1")

    await repo.flush_outbox(cid, user_id=uid)
    assert await _outbox(raw_collection, conversation) == {}
    [saved] = await _read(cid, uid, "m1")
    assert isinstance(saved, UserMessage) and saved.pinned
    assert not await _pin(cid, uid, "nope")


async def test_a_read_between_insert_and_unset_sees_the_entry_once(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_message("m1")])
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
        await _append(cid, uid, [_message(f"m{n}")])
        expected.append((n, f"m{n}"))
        reads = await asyncio.gather(
            _ids(repo, conversation),
            held.run_all(),
            _ids(repo, conversation),
            _ids(repo, conversation),
        )
        assert reads[0] == reads[2] == reads[3] == expected


async def test_a_window_takes_the_highest_seqs_across_both_stores(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_message(f"m{n}") for n in range(1, 5)])
    await held.run_all()
    await _append(cid, uid, [_message("m5"), _message("m6")])
    held.drop_all()

    heads = await repo._read_heads({"conversation_id": cid, "user_id": uid})
    [(_, newest)] = await repo._union_for(heads, EntryWindow(limit=2, newest_first=True))
    window = await conversation_log_repository.read_log(
        cid, user_id=uid, after_seq=2, through_seq=4
    )
    assert window is not None

    assert [e.seq for e in newest] == [6, 5]
    assert [e.seq for e in window] == [3, 4]


async def test_append_to_a_missing_conversation_raises_and_writes_nothing(
    repo: ConversationRepository,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    missing = f"c-{uuid.uuid4().hex}"
    with pytest.raises(ConversationNotFoundError) as raised:
        await _append(missing, "u", [_message("m1")])

    assert raised.value.message == f"conversation {missing} does not exist for this user"
    assert raised.value.meta == {"conversation_id": missing}

    assert held.held == []
    assert await raw_collection.count_documents({}) == 0
    assert await entries_collection.count_documents({}) == 0


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
        await _append(doc.conversation_id, user_id, [_flushed_at_once("m")])
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
    await _append(flushed, uid, [_reply("b1", "weekly plan")])
    await held.run_all()
    await _append(workflow, uid, [_message("w1", "weekly prompt")])
    await held.run_all()
    assert await repo.has_sent_message(uid) is False

    await _append(pending, uid, [_message("u1", "hello"), _reply("b2", "weekly recap")])
    held.drop_all()

    assert await repo.has_sent_message(uid) is True
    assert await repo.find_owner_of_message(uid, "b2") == pending
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
    repo: ConversationRepository, held: HeldFlushes
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    cid = await _chat(repo, uid)
    await _append(cid, uid, [_message("u1", "a"), _message("u2", "b")])
    await held.run_all()
    await repo.flush_outbox(cid, user_id=uid)

    assert len(await repo._find_entries(uid, {"text": {"$in": ["a", "b"]}})) == 2
    assert len(await repo._find_entries(uid, {"text": {"$in": ["a", "b"]}}, limit=1)) == 1


async def test_search_skips_a_todos_chat(repo: ConversationRepository, held: HeldFlushes) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    todo_chat = await _chat(repo, uid, todo_id="todo-1", description="needle todo")
    described = await _chat(repo, uid, description="needle notes")
    await _append(todo_chat, uid, [_message("t1", "needle")])
    held.drop_all()
    found = await repo.search(uid, pattern="needle")
    assert found.messages == []
    assert found.conversations == [
        ConversationDescriptionHit(conversation_id=described, description="needle notes")
    ]

    await _append(described, uid, [_message("d1", "needle")])
    await held.run_all()
    found = await repo.search(uid, pattern="needle")
    assert [(h.conversation_id, h.message.message_id) for h in found.messages] == [
        (described, "d1")
    ]
    assert await repo.has_sent_message(uid) is True


async def test_a_head_written_before_log_head_existed_starts_its_log_at_one(
    repo: ConversationRepository, raw_collection: Any, held: HeldFlushes
) -> None:
    await raw_collection.insert_one(
        {"conversation_id": "early", "user_id": "u", "createdAt": datetime.now(UTC).isoformat()}
    )

    assert await _append("early", "u", [_message("m1")]) == [1]
    assert await _append("early", "u", [_message("m2")]) == [2]
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
    await _append(cid, uid, [_message("m1")])
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
        {
            "conversation_id": cid,
            "user_id": uid,
            "seq": 1,
            "id": "m1",
            "kind": "user_message",
            "pinned": True,
        }
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


async def test_one_id_twice_in_a_batch_is_one_entry_holding_its_first_copy(
    repo: ConversationRepository, conversation: ConversationDocument, held: HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id

    seqs = await _append(cid, uid, [_message("d", "first"), _message("d", "second")])

    assert seqs == [1, 1]
    [saved] = await _read(cid, uid, "d")
    assert isinstance(saved, UserMessage) and saved.text == "first"
    assert await _ids(repo, conversation) == [(1, "d")]


async def test_an_append_that_loses_every_conditional_write_raises_and_commits_nothing(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    attempts: list[int] = []

    async def lost(*_: object, **__: object) -> bool:
        attempts.append(1)
        return False

    monkeypatch.setattr(mongo_log_module, "CONVERSATION_APPEND_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(conversation_log_repository, "commit_log_entry", lost)

    with pytest.raises(ConversationStoreError) as raised:
        await _append(cid, uid, [_message("m1")])

    assert raised.value.message == f"append to conversation {cid} lost every conditional write"
    assert raised.value.why == "the head moved under each of 3 attempts"
    assert raised.value.meta == {"conversation_id": cid}
    assert len(attempts) == 3
    assert await _ids(repo, conversation) == []


async def test_a_flush_of_a_conversation_deleted_under_it_takes_back_what_it_inserted(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_flushed_at_once("m1")])
    held.drop_all()
    other = await _chat(repo, uid)
    await _append(other, uid, [_flushed_at_once("kept")])
    await held.run_all()
    insert = repo._write_entries

    async def insert_then_delete(entries: Any) -> None:
        await insert(entries)
        await raw_collection.delete_one({"conversation_id": cid})

    monkeypatch.setattr(repo, "_write_entries", insert_then_delete)

    await repo.flush_outbox(cid, user_id=uid)

    assert await entries_collection.count_documents({"conversation_id": cid}) == 0
    assert await entries_collection.count_documents({"conversation_id": other}) == 1


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
    await _append(cid, uid, [_message("m1")])
    await held.run_all()
    await _append(cid, uid, [_message("m2")])
    held.drop_all()
    stale = datetime(2020, 1, 1, tzinfo=UTC)
    await raw_collection.update_one({"conversation_id": cid}, {"$set": {"updatedAt": stale}})

    assert await _pin(cid, uid, "m1")

    head = await raw_collection.find_one({"conversation_id": cid})
    assert head is not None and head["updatedAt"].year > stale.year
    assert sorted(await _outbox(raw_collection, conversation)) == ["1", "2"]
    [saved] = await _read(cid, uid, "m1")
    assert isinstance(saved, UserMessage) and saved.pinned is True


async def test_pinning_an_unknown_message_is_refused_and_leaves_updated_at(
    repo: ConversationRepository, conversation: ConversationDocument, raw_collection: Any
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    stale = datetime(2020, 1, 1, tzinfo=UTC)
    await raw_collection.update_one({"conversation_id": cid}, {"$set": {"updatedAt": stale}})

    assert not await _pin(cid, uid, "nope")

    head = await raw_collection.find_one({"conversation_id": cid})
    assert head is not None and head["updatedAt"].year == stale.year


async def test_recent_conversations_are_the_newest_limit_with_their_entries(
    repo: ConversationRepository, held: HeldFlushes
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    await _chat(repo, uid, createdAt="2026-01-01T00:00:00+00:00")
    middle = await _chat(repo, uid, createdAt="2026-01-02T00:00:00+00:00")
    newest = await _chat(repo, uid, createdAt="2026-01-03T00:00:00+00:00")
    await _append(newest, uid, [_message("m1")])
    held.drop_all()

    recent = await repo.recent_for_user(uid, limit=2)

    assert [doc.conversation_id for doc in recent] == [newest, middle]
    assert [logged.entry.id for logged in recent[0].entries] == ["m1"]


async def _orphaned(
    repo: ConversationRepository, held: HeldFlushes, raw_collection: Any, uid: str
) -> str:
    """Leave the state a delete that died between its two writes leaves: entries with no head."""
    cid = await _chat(repo, uid)
    await _append(
        cid, uid, [_message("old-0", "deleted secret"), _reply("old-1", "deleted secret")]
    )
    await held.run_all()
    await raw_collection.delete_one({"conversation_id": cid, "user_id": uid})
    return cid


async def test_a_deleted_conversations_leftover_entries_never_reach_search_or_pins(
    repo: ConversationRepository, held: HeldFlushes, raw_collection: Any
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    await _orphaned(repo, held, raw_collection, uid)
    live = await _chat(repo, uid)
    await _append(live, uid, [_message("live-1", "kept secret")])
    await held.run_all()

    found = await repo.search(uid, pattern="secret")
    assert [(h.conversation_id, h.message.message_id) for h in found.messages] == [(live, "live-1")]
    assert await repo.list_pinned_messages(uid) == []
    assert await repo.find_owner_of_message(uid, "old-1") is None


def _seqs(page: ConversationEntriesPage) -> list[int]:
    return [logged.seq for logged in page.entries]


async def test_whole_conversation_reads_return_only_the_newest_page(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: HeldFlushes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 3)
    cid, uid = conversation.conversation_id, conversation.user_id
    other = await _chat(repo, uid)
    await _append(cid, uid, [_message(f"m{n}") for n in range(1, 5)])
    await held.run_all()
    await _append(cid, uid, [_message("m5")])
    await _append(other, uid, [_message("o1")])
    held.drop_all()

    doc = await repo.get(cid, user_id=uid)
    assert doc is not None
    assert [logged.entry.id for logged in doc.entries] == ["m3", "m4", "m5"]
    assert (doc.state.head, doc.has_older, doc.cursor) == (5, True, 3)
    synced = await repo.find_updated_since(
        uid,
        [
            ConversationSyncItem(conversation_id=cid, last_updated=None),
            ConversationSyncItem(conversation_id=other, last_updated=None),
        ],
    )
    pages = {d.conversation_id: [logged.entry.id for logged in d.entries] for d in synced}
    assert pages == {cid: ["m3", "m4", "m5"], other: ["o1"]}
    [recent, _] = await repo.recent_for_user(uid, limit=2)
    assert len(recent.entries) <= 3


async def test_a_read_says_whether_older_entries_exist_beyond_its_page(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 3)
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_message(f"m{n}") for n in range(1, 4)])

    exactly = await repo.get(cid, user_id=uid)
    assert exactly is not None
    assert (_seqs(exactly), exactly.has_older, exactly.cursor) == ([1, 2, 3], False, None)

    await _append(cid, uid, [_message("m4")])
    over = await repo.get(cid, user_id=uid)
    (synced,) = await repo.find_updated_since(
        uid, [ConversationSyncItem(conversation_id=cid, last_updated=None)]
    )
    assert over is not None
    assert (_seqs(over), over.has_older, over.cursor) == ([2, 3, 4], True, 2)
    assert (synced.has_older, synced.cursor) == (True, 2)


async def test_entries_before_a_seq_page_back_to_the_first(
    repo: ConversationRepository, conversation: ConversationDocument
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    await _append(cid, uid, [_message(f"m{n}") for n in range(1, 6)])

    page = await repo.read_entries_before(cid, user_id=uid, before_seq=5, limit=2)
    last = await repo.read_entries_before(cid, user_id=uid, before_seq=3, limit=2)
    exact = await repo.read_entries_before(cid, user_id=uid, before_seq=3, limit=3)

    assert page is not None and last is not None and exact is not None
    assert (_seqs(page), page.has_older, page.cursor) == ([3, 4], True, 3)
    assert (_seqs(last), last.has_older, last.cursor) == ([1, 2], False, None)
    assert (_seqs(exact), exact.has_older) == ([1, 2], False)
    assert page.state.head == 5
    assert await repo.read_entries_before("missing", user_id=uid, before_seq=3, limit=2) is None


async def test_a_page_never_splits_a_reply_from_the_settle_that_completes_it(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 2)
    cid, uid = conversation.conversation_id, conversation.user_id
    settle = ReplySettled(
        id="settle-r1",
        reply_id="r1",
        outcome=ReplyOutcome.ANSWERED,
        answers=("m1",),
        through=1,
        quote_target=None,
    )
    await _append(
        cid, uid, [_message("m1"), _reply("r1", "on it"), _message("m2"), _message("m3"), settle]
    )

    doc = await repo.get(cid, user_id=uid)
    older = await repo.read_entries_before(cid, user_id=uid, before_seq=6, limit=2)

    assert doc is not None and older is not None
    assert (_seqs(doc), doc.has_older, doc.cursor) == ([2, 3, 4, 5], True, 2)
    assert _seqs(older) == [2, 3, 4, 5]
    rest = await repo.read_entries_before(cid, user_id=uid, before_seq=2, limit=2)
    assert rest is not None and (_seqs(rest), rest.has_older) == ([1], False)
