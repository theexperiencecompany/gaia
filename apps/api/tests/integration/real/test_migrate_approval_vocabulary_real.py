"""The one-time rewrite moves every stored old approval value onto the new fields, once."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import JsonValue
import pytest
from scripts.approval_vocabulary import CARD_STATUSES, RECORD_STATUSES
from scripts.migrate_approval_vocabulary import (
    LEDGER,
    LEDGER_STATES,
    LOG_DECISIONS,
    RECORDS,
    rewrite,
    unreadable_entries,
    verify,
)

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.db.mongodb.indexes import CONVERSATION_ENTRY_INDEXES
from app.db.repositories.conversation_entries import log_document, logged_of
from app.db.repositories.conversation_migration_guard import (
    RENAMED_ENTRY_FIELDS,
    RENAMED_ENTRY_SHAPED,
    ConversationMigrationGuard,
    refuse_unmigrated_conversations,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    LoggedEntry,
)
from app.models.conversation_models import StoredEntry
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.describe import describe_call
from app.services.hil.when import UserClock
from app.utils.errors import UnmigratedConversationError
from app.utils.timezone import Timezone
from shared.py.approvals import ActionResult, ApprovalDecider
from tests.unit.services.conversation.log_helpers import barge, decided, fired, logged

pytestmark = [pytest.mark.integration, pytest.mark.service]
NOW = datetime(2026, 11, 1, tzinfo=UTC)
RENAMED_CONVERSATION = "c-renamed"


@pytest.fixture
async def db(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[AsyncIOMotorDatabase]:
    for name in (LEDGER, RECORDS, CONVERSATION_ENTRIES_COLLECTION):
        await mongo_db[name].drop()
    yield mongo_db
    for name in (LEDGER, RECORDS, CONVERSATION_ENTRIES_COLLECTION):
        await mongo_db[name].drop()


def _card(status: str) -> dict[str, Any]:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "data": {"approval_id": status, "status": status},
    }


async def _seed_every_old_value(db: AsyncIOMotorDatabase) -> None:
    await db[LEDGER].insert_many(
        [
            {
                "approval_id": state,
                "conversation_id": "c1",
                "fingerprint": state,
                "tool_name": "T",
                "state": state,
                "v": 1,
            }
            for state in LEDGER_STATES
        ]
    )
    await db[RECORDS].insert_many(
        [
            {
                "_id": status,
                "approval_id": status,
                "user_id": "u1",
                "conversation_id": "c1",
                "stream_id": "s1",
                "tool_name": "T",
                "status": status,
                "expires_at": NOW,
            }
            for status in RECORD_STATUSES
        ]
    )
    entries = db[CONVERSATION_ENTRIES_COLLECTION]
    await entries.insert_many(
        [
            {
                "kind": "approval_decided",
                "id": f"approval:{d}:decided",
                "approval_id": d,
                "decision": d,
            }
            for d in LOG_DECISIONS
        ]
    )
    # Every card status in one entry, beside a card that is not an approval.
    others = {"tool_name": "web_search", "data": {"status": "approved"}}
    await entries.insert_one(
        {"kind": "reply", "reply_id": "r1", "tool_data": [others, *map(_card, CARD_STATUSES)]}
    )


async def test_a_dry_run_counts_every_old_value_and_writes_nothing(
    db: AsyncIOMotorDatabase,
) -> None:
    await _seed_every_old_value(db)

    report = await rewrite(db, apply=False)

    expected = len(LEDGER_STATES) + len(RECORD_STATUSES) + len(LOG_DECISIONS) + len(CARD_STATUSES)
    assert report.left == expected
    assert (await verify(db)).left == len(LEDGER_STATES) + len(RECORD_STATUSES) + len(
        LOG_DECISIONS
    ) + 1


async def test_apply_moves_every_old_value_onto_the_new_fields(db: AsyncIOMotorDatabase) -> None:
    await _seed_every_old_value(db)

    await rewrite(db, apply=True)

    assert (await verify(db)).left == 0
    rows = {row["approval_id"]: row async for row in db[LEDGER].find({}, {"_id": 0})}
    assert {k: (r["outcome"], r["action"]) for k, r in rows.items()} == LEDGER_STATES
    assert "state" not in rows["pending"]
    # An undecided row keeps explicit nulls: the live unique index matches on them.
    assert ("outcome", None) in rows["pending"].items()
    assert ApprovalLedgerDocument.model_validate(rows["executed"]).action is ActionResult.EXECUTED
    records = {r["_id"]: r async for r in db[RECORDS].find({})}
    assert {k: (r["outcome"], r["decider"]) for k, r in records.items()} == RECORD_STATUSES
    assert ApprovalDecider(records["auto_approved"]["decider"]) is ApprovalDecider.AUTO
    entries = db[CONVERSATION_ENTRIES_COLLECTION]
    decided = [
        ApprovalDecided.model_validate(e)
        async for e in entries.find({"kind": "approval_decided"}, {"_id": 0})
    ]
    assert {d.approval_id: (d.outcome, d.decider) for d in decided} == LOG_DECISIONS
    reply = await entries.find_one({"reply_id": "r1"})
    assert reply is not None
    other, *cards = reply["tool_data"]
    assert other == {"tool_name": "web_search", "data": {"status": "approved"}}
    assert {
        c["data"]["approval_id"]: (c["data"]["outcome"], c["data"]["decider"], c["data"]["action"])
        for c in cards
    } == {
        "pending": (None, None, None),
        "approved": ("approved", "user", None),
        "denied": ("denied", "user", None),
        "timeout": ("expired", None, None),
        "abandoned": ("cancelled", None, None),
        "auto_approved": ("approved", "auto", None),
        "cancelled": ("cancelled", None, None),
        "revoked": ("withdrawn", None, None),
        "executed": ("approved", "user", "executed"),
        "failed": ("approved", "user", "failed"),
        "unknown": ("approved", "user", "unknown"),
    }
    assert all("status" not in c["data"] for c in cards)


async def test_a_second_apply_finds_nothing_left(db: AsyncIOMotorDatabase) -> None:
    await _seed_every_old_value(db)
    await rewrite(db, apply=True)
    before = [doc async for doc in db[LEDGER].find({}).sort("approval_id")]

    again = await rewrite(db, apply=True)

    assert again.left == 0
    assert [doc async for doc in db[LEDGER].find({}).sort("approval_id")] == before


async def test_apply_drops_the_indexes_keyed_on_old_fields(db: AsyncIOMotorDatabase) -> None:
    await db[LEDGER].create_index([("conversation_id", 1), ("state", 1)])
    await db[RECORDS].create_index([("status", 1), ("expires_at", 1)])

    await rewrite(db, apply=True)

    assert "conversation_id_1_state_1" not in await db[LEDGER].index_information()
    assert "status_1_expires_at_1" not in await db[RECORDS].index_information()


def _stored(seq: int, entry: Entry) -> tuple[LoggedEntry, dict[str, Any]]:
    """Return an entry as the current build logs it, and its document to age into an old shape."""
    entry_logged = logged(seq, entry)
    return entry_logged, log_document(RENAMED_CONVERSATION, "u1", entry_logged)


def _every_renamed_shape() -> list[tuple[LoggedEntry, dict[str, Any]]]:
    """One entry per field the stack renamed, written the way the build before the rename wrote it."""
    args: dict[str, JsonValue] = {"title": "ap-1"}
    requested = ApprovalRequested(
        id="approval:a1",
        task_id="t1",
        approval_id="a1",
        description=describe_call(
            "create_todo", args, "todos", clock=UserClock(Timezone.parse("UTC"), NOW)
        ),
        gated_tool_name="create_todo",
        integration_name="todos",
        args_preview=args,
    )
    asked, asked_doc = _stored(1, requested)
    del asked_doc["description"]
    asked_doc["summary"] = "Create todo (todos); title: ap-1"
    answered, answered_doc = _stored(2, decided("approval:a1:decided", "a1"))
    del answered_doc["outcome"], answered_doc["decider"]
    answered_doc["decision"] = "approve"
    heard = "héllo wörld \N{WAVING HAND SIGN}"
    cut, cut_doc = _stored(3, barge("barge:1", "r1", heard_through=len(heard)))
    del cut_doc["heard_through"]
    cut_doc["heard_text"] = heard
    fire, fire_doc = _stored(4, fired("fire:1"))
    fire_doc["run"]["reservation"] = "res_1"
    return [(asked, asked_doc), (answered, answered_doc), (cut, cut_doc), (fire, fire_doc)]


async def _read_back(db: AsyncIOMotorDatabase) -> list[LoggedEntry]:
    entries = db[CONVERSATION_ENTRIES_COLLECTION].find({"conversation_id": RENAMED_CONVERSATION})
    return [logged_of(StoredEntry.model_validate(doc)) async for doc in entries.sort("seq")]


async def test_apply_turns_every_renamed_entry_field_into_the_entry_the_reader_reads(
    db: AsyncIOMotorDatabase,
) -> None:
    shapes = _every_renamed_shape()
    await db[CONVERSATION_ENTRIES_COLLECTION].insert_many([doc for _, doc in shapes])
    assert len(await unreadable_entries(db)) == len(shapes) == len(RENAMED_ENTRY_FIELDS)
    assert await ConversationMigrationGuard().first_renamed() == RENAMED_CONVERSATION

    await rewrite(db, apply=True)

    assert await _read_back(db) == [entry for entry, _ in shapes]
    assert await unreadable_entries(db) == []
    assert (await verify(db)).left == 0
    assert await ConversationMigrationGuard().first_renamed() is None


async def test_a_dry_run_counts_each_renamed_field_and_leaves_it_unreadable(
    db: AsyncIOMotorDatabase,
) -> None:
    await db[CONVERSATION_ENTRIES_COLLECTION].insert_many(
        [doc for _, doc in _every_renamed_shape()]
    )

    report = await rewrite(db, apply=False)

    # Each old entry counted once: the decision under its value, every other field under its name.
    assert report.left == len(RENAMED_ENTRY_FIELDS)
    assert len(await unreadable_entries(db)) == len(RENAMED_ENTRY_FIELDS)


async def test_verify_names_an_entry_no_pass_can_convert(db: AsyncIOMotorDatabase) -> None:
    _, doc = _stored(1, fired("fire:1"))
    del doc["run"]["attribution"]
    await db[CONVERSATION_ENTRIES_COLLECTION].insert_one(doc)

    await rewrite(db, apply=True)

    (unreadable,) = await unreadable_entries(db)
    assert RENAMED_CONVERSATION in unreadable and "workflow_fired" in unreadable


async def test_the_boot_check_refuses_a_renamed_field_found_through_its_index(
    db: AsyncIOMotorDatabase,
) -> None:
    entries = db[CONVERSATION_ENTRIES_COLLECTION]
    for keys, options in CONVERSATION_ENTRY_INDEXES:
        await entries.create_index(keys, **options)
    await entries.insert_one(_every_renamed_shape()[2][1])

    with pytest.raises(UnmigratedConversationError, match="migrate_approval_vocabulary --apply"):
        await refuse_unmigrated_conversations()
    plan = (await entries.find(RENAMED_ENTRY_SHAPED).explain())["queryPlanner"]["winningPlan"]
    assert str(plan).count("IXSCAN") == len(RENAMED_ENTRY_FIELDS)
