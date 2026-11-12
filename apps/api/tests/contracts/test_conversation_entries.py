"""The conversation-entries append protocol against real Mongo: one seq allocator, an outbox, a union read."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime
from typing import Any
import uuid

import pytest

from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_entries import EntryWindow
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationDocument
from app.utils.errors import ConversationNotFoundError, UnmigratedConversationError

# Every test here writes entries, so each needs the collection with its unique indexes.
pytestmark = pytest.mark.usefixtures("entries_collection")


class _HeldFlushes:
    """Stands in for the flush spawner: keeps each flush coroutine until the test runs or drops it."""

    def __init__(self) -> None:
        self.held: list[Coroutine[Any, Any, Any]] = []

    def __call__(self, operation: str, coro: Coroutine[Any, Any, Any], **_: object) -> None:
        self.held.append(coro)

    async def run_all(self) -> None:
        held, self.held = self.held, []
        for coro in held:
            await coro

    def drop_all(self) -> None:
        held, self.held = self.held, []
        for coro in held:
            coro.close()


@pytest.fixture
def repo(raw_collection: Any) -> ConversationRepository:
    return ConversationRepository()


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> Iterator[_HeldFlushes]:
    flushes = _HeldFlushes()
    monkeypatch.setattr(conversations_module, "spawn_logged_task", flushes)
    yield flushes
    flushes.drop_all()


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
    return [(entry.seq, entry.message.message_id or "") for entry in entries]


async def _outbox(raw_collection: Any, doc: ConversationDocument) -> dict[str, Any]:
    head = await raw_collection.find_one({"conversation_id": doc.conversation_id})
    assert head is not None
    return dict(head.get("outbox") or {})


async def test_concurrent_appends_take_every_seq_once_in_order(
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
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
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
) -> None:
    [seq] = await repo.append(
        conversation.conversation_id, user_id=conversation.user_id, entries=[_message("m1")]
    )

    assert held.held, "the flush must not have run yet"
    assert await _ids(repo, conversation) == [(seq, "m1")]


async def test_a_flush_that_never_ran_is_finished_by_the_next_append_or_flush_outbox(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: _HeldFlushes,
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
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
) -> None:
    cid, uid = conversation.conversation_id, conversation.user_id
    first = await repo.append(cid, user_id=uid, entries=[_message("same")])
    again = await repo.append(cid, user_id=uid, entries=[_message("same")])
    await held.run_all()
    after_flush = await repo.append(cid, user_id=uid, entries=[_message("same")])
    racing = await asyncio.gather(
        repo.append(cid, user_id=uid, entries=[_message("twin")]),
        repo.append(cid, user_id=uid, entries=[_message("twin")]),
    )
    await held.run_all()

    assert first == again == after_flush == [1]
    assert racing[0] == racing[1] == [2]
    assert await _ids(repo, conversation) == [(1, "same"), (2, "twin")]


async def test_a_batch_with_one_known_id_appends_only_the_new_ones(
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
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
    held: _HeldFlushes,
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


async def test_a_read_between_insert_and_unset_sees_the_entry_once(
    repo: ConversationRepository,
    conversation: ConversationDocument,
    held: _HeldFlushes,
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
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
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
    repo: ConversationRepository, conversation: ConversationDocument, held: _HeldFlushes
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
    held: _HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        await repo.append(f"c-{uuid.uuid4().hex}", user_id="u", entries=[_message("m1")])

    assert held.held == []
    assert await raw_collection.count_documents({}) == 0
    assert await entries_collection.count_documents({}) == 0


async def test_an_unmigrated_conversation_is_refused_by_name(
    repo: ConversationRepository, raw_collection: Any, held: _HeldFlushes
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
    repo: ConversationRepository, held: _HeldFlushes, entries_collection: Any
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
    await repo.delete_for_todos("u3", ["todo-1"])
    assert await entries_collection.count_documents({"user_id": "u3"}) == 1
    await repo.delete_all_chats_for_user("u3")
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
    repo: ConversationRepository, held: _HeldFlushes
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


async def test_search_skips_a_todos_chat_and_cross_reads_refuse_unmigrated_data(
    repo: ConversationRepository, held: _HeldFlushes, raw_collection: Any
) -> None:
    uid = f"u-{uuid.uuid4().hex}"
    todo_chat = await _chat(repo, uid, todo_id="todo-1")
    await repo.append(todo_chat, user_id=uid, entries=[_message("t1", "needle")])
    held.drop_all()
    assert (await repo.search(uid, pattern="needle")).messages == []

    await raw_collection.insert_one(
        {"conversation_id": "old", "user_id": uid, "messages": [{"type": "user", "response": "x"}]}
    )
    with pytest.raises(UnmigratedConversationError):
        await repo.has_sent_message(uid)
