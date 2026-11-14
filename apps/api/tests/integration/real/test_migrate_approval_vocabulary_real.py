"""The one-time rewrite moves every stored old approval value onto the new fields, once."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.conversation_log_models import ApprovalDecided
from app.models.hil_models import ApprovalLedgerDocument
from app.scripts.migrate_approval_vocabulary import (
    CARD_STATUSES,
    LEDGER,
    LEDGER_STATES,
    LOG_DECISIONS,
    RECORD_STATUSES,
    RECORDS,
    rewrite,
    verify,
)
from shared.py.analytics.catalog.hil import ActionResult, ApprovalDecider

pytestmark = [pytest.mark.integration, pytest.mark.service]
NOW = datetime(2026, 11, 1, tzinfo=UTC)


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
