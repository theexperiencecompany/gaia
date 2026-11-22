"""The pre-boot cutover against real Mongo: migrates and verifies only what the boot check refuses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import re
import time
from typing import Any
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
import pytest
from scripts.migrate_approval_vocabulary import LEDGER
from scripts.migrate_conversation_entries import __main__ as entries
from scripts.migrate_conversation_entries.migration import HeadRef, conversation_entries_migration
from scripts.migrate_conversations import CATCH_UP_NEEDED_EXIT, check, migrate_conversations

from app.db.mongodb.indexes import UNMIGRATED_HEAD_KEYS, UNMIGRATED_HEAD_OPTIONS
from app.db.repositories.conversation_migration_guard import refuse_unmigrated_conversations
from app.utils.errors import UnmigratedConversationError
from tests.helpers import worker_mongo_db_name

pytestmark = pytest.mark.usefixtures("entries_collection")

USER = "u-cutover"
_DATE = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
#: Enough heads that verifying all of them takes minutes, so a pass over every head cannot pass.
_GENERATED_HEADS = 2000
#: A catch-up of three heads among the generated ones finishes well inside this.
_CATCH_UP_SECONDS = 10


@pytest.fixture
async def db(mongodb_url: str) -> AsyncIterator[AsyncIOMotorDatabase]:
    """Yield the worker's test database, where the vocabulary rewrite reads the ledger."""
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url, tz_aware=True)
    database = client[worker_mongo_db_name()]
    yield database
    await database[LEDGER].drop()
    client.close()


async def _legacy(raw_collection: AsyncIOMotorCollection, **message: object) -> str:
    """Insert a conversation as the old build stored it: its messages embedded in the head."""
    conversation_id = f"c-{uuid.uuid4().hex}"
    await raw_collection.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": USER,
            "description": "legacy",
            "createdAt": _DATE,
            "updatedAt": datetime(2026, 1, 1, tzinfo=UTC),
            "messages": [
                {"type": "user", "response": "hi", "message_id": "m1", "date": _DATE, **message}
            ],
            "source": "web",
        }
    )
    return conversation_id


async def test_an_old_install_boots_after_one_run_and_a_second_run_has_nothing_to_do(
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conversation_id = await _legacy(raw_collection)
    await db[LEDGER].insert_one({"approval_id": "a1", "state": "approved"})
    with pytest.raises(UnmigratedConversationError):
        await refuse_unmigrated_conversations()

    assert await migrate_conversations(db) == 0

    await refuse_unmigrated_conversations()
    assert await entries_collection.count_documents({"conversation_id": conversation_id}) == 1
    ledger_row: dict[str, Any] | None = await db[LEDGER].find_one({"approval_id": "a1"})
    assert ledger_row is not None and "state" not in ledger_row
    capsys.readouterr()

    assert await migrate_conversations(db) == 0
    assert capsys.readouterr().out.splitlines() == ["Every conversation is in this build's shape."]


async def test_check_names_a_pending_catch_up_writes_nothing_and_passes_once_it_ran(
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conversation_id = await _legacy(raw_collection)
    head_before = await raw_collection.find_one({"conversation_id": conversation_id})

    assert await check(db) == CATCH_UP_NEEDED_EXIT

    assert f"A catch-up is needed: conversation {conversation_id}" in capsys.readouterr().out
    assert await raw_collection.find_one({"conversation_id": conversation_id}) == head_before
    assert await entries_collection.count_documents({}) == 0
    assert await migrate_conversations(db) == 0
    capsys.readouterr()
    assert await check(db) == 0
    assert capsys.readouterr().out.splitlines() == ["Every conversation is in this build's shape."]


async def test_check_counts_old_approval_values_as_a_pending_catch_up(
    db: AsyncIOMotorDatabase, capsys: pytest.CaptureFixture[str]
) -> None:
    await db[LEDGER].insert_one({"approval_id": "a1", "state": "approved"})

    assert await check(db) == CATCH_UP_NEEDED_EXIT

    assert "1 stored approval values in the old vocabulary" in capsys.readouterr().out
    assert await db[LEDGER].count_documents({"state": {"$exists": True}}) == 1


async def test_a_conversation_the_log_refuses_fails_the_run_and_the_boot_stays_refused(
    raw_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _legacy(raw_collection, selectedTool="not an identifier!")

    assert await migrate_conversations(db) == 1

    assert "Every conversation is in this build's shape." not in capsys.readouterr().out
    with pytest.raises(UnmigratedConversationError):
        await refuse_unmigrated_conversations()


async def test_a_conversation_a_verify_found_wrong_fails_the_run_until_it_verifies(
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conversation_id = await _legacy(raw_collection)
    assert await migrate_conversations(db) == 0
    entry = {"conversation_id": conversation_id, "id": "m1"}
    await entries_collection.update_one(entry, {"$set": {"text": "tampered"}})
    assert await entries.verify_all() == 1
    capsys.readouterr()

    assert await migrate_conversations(db) == 1

    out = capsys.readouterr().out
    assert f"conversation {conversation_id} still holds a failed migration pass or verify" in out
    assert "Every conversation is in this build's shape." not in out
    await entries_collection.update_one(entry, {"$set": {"text": "hi"}})
    assert await migrate_conversations(db) == 0
    await refuse_unmigrated_conversations()


async def test_messages_the_old_build_pushes_onto_a_migrated_head_refuse_the_boot_until_merged(
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
) -> None:
    conversation_id = await _legacy(raw_collection)
    assert await migrate_conversations(db) == 0
    pushed = [
        {"type": "user", "response": "still there?", "message_id": "m2", "date": _DATE},
        {"type": "bot", "response": "yes", "message_id": "m3", "date": _DATE},
    ]
    await raw_collection.update_one(
        {"conversation_id": conversation_id}, {"$push": {"messages": {"$each": pushed}}}
    )

    with pytest.raises(UnmigratedConversationError, match=conversation_id):
        await refuse_unmigrated_conversations()
    assert await migrate_conversations(db) == 0

    await refuse_unmigrated_conversations()
    ids = await entries_collection.distinct("id", {"conversation_id": conversation_id})
    assert {"m1", "m2", "m3"} <= set(ids)


async def test_the_catch_up_after_a_full_pass_visits_only_the_heads_written_since(
    raw_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await raw_collection.create_index(UNMIGRATED_HEAD_KEYS, **UNMIGRATED_HEAD_OPTIONS)
    message = {"type": "user", "response": "hi", "message_id": "m1", "date": _DATE}
    heads = [
        {
            "conversation_id": f"c-{n}",
            "user_id": USER,
            "createdAt": _DATE,
            "messages": [message],
            "source": "web",
        }
        for n in range(_GENERATED_HEADS)
    ]
    await raw_collection.insert_many(heads)
    assert await entries.migrate_all(apply=True) == 0
    written = [f"c-{n}" for n in (0, _GENERATED_HEADS // 2, _GENERATED_HEADS - 1)]
    late = {"type": "bot", "response": "late", "message_id": "m2", "date": _DATE}
    await raw_collection.update_many(
        {"conversation_id": {"$in": written}}, {"$push": {"messages": late}}
    )
    capsys.readouterr()

    started = time.perf_counter()
    assert await migrate_conversations(db) == 0
    elapsed = time.perf_counter() - started

    out = capsys.readouterr().out
    assert sorted(re.findall(r"\[merged\] (c-\d+)", out)) == sorted(written)
    assert f"Verified {len(written)} conversations: 0 with mismatches." in out
    assert elapsed < _CATCH_UP_SECONDS


async def test_a_trim_that_failed_an_earlier_catch_up_verifies_and_clears_its_failure(
    raw_collection: AsyncIOMotorCollection,
    db: AsyncIOMotorDatabase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conversation_id = await _legacy(raw_collection)
    later = [
        {"type": "bot", "response": "first", "message_id": "m2", "date": _DATE},
        {"type": "user", "response": "again", "message_id": "m3", "date": _DATE},
        {"type": "bot", "response": "second", "message_id": "m4", "date": _DATE},
    ]
    await raw_collection.update_one(
        {"conversation_id": conversation_id}, {"$push": {"messages": {"$each": later}}}
    )
    assert await migrate_conversations(db) == 0
    # The old build keeps a todo chat to its newest messages on every append.
    await raw_collection.update_one(
        {"conversation_id": conversation_id}, {"$pop": {"messages": -1}}
    )
    head = await raw_collection.find_one({"conversation_id": conversation_id})
    assert head is not None
    ref = HeadRef(str(head["_id"]), conversation_id, USER)
    # An earlier catch-up merged the trimmed array, then recorded its verify failure.
    await conversation_entries_migration.migrate(ref, apply=True)
    await conversation_entries_migration.mark_failed(ref, "verify: 1 mismatches")
    capsys.readouterr()

    assert await migrate_conversations(db) == 0

    out = capsys.readouterr().out
    assert "Verified 1 conversations: 0 with mismatches." in out
    assert out.splitlines()[-1] == "Every conversation is in this build's shape."
    assert await conversation_entries_migration.first_failed() is None
    await refuse_unmigrated_conversations()
    assert await check(db) == 0
