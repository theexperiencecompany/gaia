"""The pre-boot cutover against real Mongo: migrates and verifies only what the boot check refuses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
import pytest
from scripts.migrate_approval_vocabulary import LEDGER
from scripts.migrate_conversation_entries import __main__ as entries
from scripts.migrate_conversations import migrate_conversations

from app.db.repositories.conversation_migration_guard import refuse_unmigrated_conversations
from app.utils.errors import UnmigratedConversationError
from tests.helpers import worker_mongo_db_name

pytestmark = pytest.mark.usefixtures("entries_collection")

USER = "u-cutover"
_DATE = datetime(2026, 1, 1, tzinfo=UTC).isoformat()


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
