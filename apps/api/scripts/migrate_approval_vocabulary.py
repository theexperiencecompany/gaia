#!/usr/bin/env python3
"""Rewrite stored approvals into ApprovalOutcome / ApprovalDecider / ActionResult.

Four stores spoke their own words for how an approval ended: the ledger's
``state``, the approval record's ``status``, the log entry's ``decision`` and the
card payload's ``data.status``. Each old value becomes the outcome, who decided
and what the action did (the module's maps), and the old field is unset. Every
other entry field this stack renamed is rewritten too (RENAMED_ENTRY_FIELDS: an
approval's summary becomes the description the gate writes for the same call,
a barge-in's heard_text its length, a fire's reservation goes).
Dry run by default. Safe to re-run: every write matches only an old field.

Run after the conversation-entries cutover's final pass, while the old build is
fenced, then deploy: --apply, then --verify (exits 1 while any old value is left
or any entry fails to read as the current build reads it). The new build refuses
to boot while an entry holds a renamed field.

Usage::

    cd apps/api
    uv run python -m scripts.migrate_approval_vocabulary            # report only
    uv run python -m scripts.migrate_approval_vocabulary --apply
    uv run python -m scripts.migrate_approval_vocabulary --verify
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.config.settings import settings
from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.db.repositories.conversation_entries import logged_of
from app.db.repositories.conversation_migration_guard import RENAMED_ENTRY_FIELDS
from app.models.conversation_log_models import EntryKind
from app.models.conversation_models import StoredEntry
from app.services.hil.describe import describe_call
from app.services.hil.when import UserClock
from app.utils.timezone import Timezone
from shared.py.approvals import ActionResult, ApprovalDecider, ApprovalOutcome

LEDGER = "approval_ledger"
RECORDS = "hil_approvals"
APPROVED, DENIED = ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED
USER, AUTO = ApprovalDecider.USER, ApprovalDecider.AUTO

#: Ledger state -> (outcome, action). Old data cannot tell a Stop from an agent revoke: withdrawn.
LEDGER_STATES: dict[str, tuple[ApprovalOutcome | None, ActionResult | None]] = {
    "pending": (None, None),
    "approved": (APPROVED, None),
    "denied": (DENIED, None),
    "revoked": (ApprovalOutcome.WITHDRAWN, None),
    "executing": (APPROVED, ActionResult.EXECUTING),
    "executed": (APPROVED, ActionResult.EXECUTED),
    "failed": (APPROVED, ActionResult.FAILED),
    "unknown": (APPROVED, ActionResult.UNKNOWN),
}
#: Approval record status -> (outcome, decider). abandoned was written by a Stop or a moved-on reply.
RECORD_STATUSES: dict[str, tuple[ApprovalOutcome | None, ApprovalDecider | None]] = {
    "pending": (None, None),
    "approved": (APPROVED, USER),
    "denied": (DENIED, USER),
    "timeout": (ApprovalOutcome.EXPIRED, None),
    "abandoned": (ApprovalOutcome.CANCELLED, None),
    "auto_approved": (APPROVED, AUTO),
}
#: Log entry decision -> (outcome, decider).
LOG_DECISIONS: dict[str, tuple[ApprovalOutcome, ApprovalDecider | None]] = {
    "approve": (APPROVED, USER),
    "deny": (DENIED, USER),
    "timeout": (ApprovalOutcome.EXPIRED, None),
    "abandon": (ApprovalOutcome.CANCELLED, None),
}
#: Card status -> (outcome, decider, action): the record's words plus the ledger's.
CARD_STATUSES: dict[
    str, tuple[ApprovalOutcome | None, ApprovalDecider | None, ActionResult | None]
] = {
    **{status: (outcome, decider, None) for status, (outcome, decider) in RECORD_STATUSES.items()},
    "cancelled": (ApprovalOutcome.CANCELLED, None, None),
    "revoked": (ApprovalOutcome.WITHDRAWN, None, None),
    "executed": (APPROVED, USER, ActionResult.EXECUTED),
    "failed": (APPROVED, USER, ActionResult.FAILED),
    "unknown": (APPROVED, USER, ActionResult.UNKNOWN),
}

_CARD = "tool_data.$[card].data"
#: Indexes keyed on the old fields; the new build creates their replacements at startup.
OLD_INDEXES: tuple[tuple[str, str], ...] = (
    (LEDGER, "conv_fingerprint_live_unique"),
    (LEDGER, "conversation_id_1_state_1"),
    (LEDGER, "state_1_executing_started_at_1"),
    (RECORDS, "conversation_id_1_status_1"),
    (RECORDS, "status_1_expires_at_1"),
    (RECORDS, "status_1_resumed_at_1_decided_at_1"),
)
#: The renamed entry fields this module rewrites by name; LOG_DECISIONS rewrites decision value by value.
RENAMED_HERE = tuple(name for name in RENAMED_ENTRY_FIELDS if name != "decision")


@dataclass
class Report:
    """How many stored documents still carry, or were moved off, each old value."""

    counts: dict[str, int] = field(default_factory=dict)

    @property
    def left(self) -> int:
        """Return how many old values the report counted."""
        return sum(self.counts.values())


class _GatedCall(BaseModel):
    """The call an old approval entry asked about, which its description is built from."""

    model_config = ConfigDict(extra="ignore")

    gated_tool_name: str
    args_preview: dict[str, JsonValue] = Field(default_factory=dict)
    integration_name: str | None = None
    at: datetime


class _EntryRef(BaseModel):
    """Where an unreadable entry sits, read loosely so a broken entry can still be named."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str | None = None
    seq: int | None = None
    kind: str | None = None


def _card_filter(status: str) -> dict[str, object]:
    return {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data.status": status}


async def _rename_entry_fields(
    entries: AsyncIOMotorCollection, report: Report, *, apply: bool
) -> None:
    """Count, and with apply rewrite, every renamed entry field the decision maps do not cover."""
    for name in RENAMED_HERE:
        report.counts[f"entry field {name}"] = await entries.count_documents(
            {name: {"$exists": True}}
        )
    if not apply:
        return
    async for raw in entries.find({"summary": {"$exists": True}}):
        call = _GatedCall.model_validate(raw)
        # Dates read as of the ask, in UTC: an old entry does not carry the user's zone.
        description = describe_call(
            call.gated_tool_name,
            call.args_preview,
            call.integration_name,
            clock=UserClock(Timezone.utc(), call.at),
        )
        await entries.update_one(
            {"_id": raw["_id"]},
            {"$set": {"description": description.model_dump()}, "$unset": {"summary": ""}},
        )
    # heard_through counts characters (code points), as the reply text is sliced.
    await entries.update_many(
        {"heard_text": {"$exists": True}},
        [{"$set": {"heard_through": {"$strLenCP": "$heard_text"}}}, {"$unset": "heard_text"}],
    )
    await entries.update_many(
        {"run.reservation": {"$exists": True}}, {"$unset": {"run.reservation": ""}}
    )


async def rewrite(db: AsyncIOMotorDatabase, *, apply: bool) -> Report:
    """Count every old value and, with apply, rewrite it; returns the counts seen."""
    report = Report()
    ledger, records, entries = db[LEDGER], db[RECORDS], db[CONVERSATION_ENTRIES_COLLECTION]
    for state, (outcome, action) in LEDGER_STATES.items():
        query: dict[str, object] = {"state": state}
        report.counts[f"ledger state={state}"] = await ledger.count_documents(query)
        if apply:
            await ledger.update_many(
                query, {"$set": {"outcome": outcome, "action": action}, "$unset": {"state": ""}}
            )
    for status, (outcome, decider) in RECORD_STATUSES.items():
        query = {"status": status}
        report.counts[f"record status={status}"] = await records.count_documents(query)
        if apply:
            await records.update_many(
                query,
                {"$set": {"outcome": outcome, "decider": decider}, "$unset": {"status": ""}},
            )
    for decision, (outcome, decider) in LOG_DECISIONS.items():
        query = {"kind": EntryKind.APPROVAL_DECIDED.value, "decision": decision}
        report.counts[f"log decision={decision}"] = await entries.count_documents(query)
        if apply:
            await entries.update_many(
                query,
                {"$set": {"outcome": outcome, "decider": decider}, "$unset": {"decision": ""}},
            )
    for status, (outcome, decider, action) in CARD_STATUSES.items():
        query = {"tool_data": {"$elemMatch": _card_filter(status)}}
        report.counts[f"card status={status}"] = await entries.count_documents(query)
        if apply:
            await entries.update_many(
                query,
                {
                    "$set": {
                        f"{_CARD}.outcome": outcome,
                        f"{_CARD}.decider": decider,
                        f"{_CARD}.action": action,
                    },
                    "$unset": {f"{_CARD}.status": ""},
                },
                array_filters=[
                    {f"card.{key}": value for key, value in _card_filter(status).items()}
                ],
            )
    for collection, index in OLD_INDEXES:
        present = index in await db[collection].index_information()
        report.counts[f"index {collection}.{index}"] = int(present)
        if apply and present:
            await db[collection].drop_index(index)
    await _rename_entry_fields(entries, report, apply=apply)
    return report


async def verify(db: AsyncIOMotorDatabase) -> Report:
    """Count documents still holding any old field, whatever its value."""
    entries = db[CONVERSATION_ENTRIES_COLLECTION]
    card = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data.status": {"$exists": True}}
    return Report(
        {
            "ledger state": await db[LEDGER].count_documents({"state": {"$exists": True}}),
            "record status": await db[RECORDS].count_documents({"status": {"$exists": True}}),
            "log decision": await entries.count_documents(
                {"kind": EntryKind.APPROVAL_DECIDED.value, "decision": {"$exists": True}}
            ),
            "card status": await entries.count_documents({"tool_data": {"$elemMatch": card}}),
            "renamed entry field": await entries.count_documents(
                {"$or": [{name: {"$exists": True}} for name in RENAMED_HERE]}
            ),
        }
    )


async def unreadable_entries(db: AsyncIOMotorDatabase) -> list[str]:
    """Name every stored entry the current build fails to read, with the first reason it fails."""
    unreadable: list[str] = []
    async for raw in db[CONVERSATION_ENTRIES_COLLECTION].find({}):
        try:
            logged_of(StoredEntry.model_validate(raw))
        except ValidationError as error:
            ref = _EntryRef.model_validate(raw)
            first = error.errors()[0]
            unreadable.append(
                f"conversation {ref.conversation_id} seq {ref.seq} ({ref.kind}): "
                f"{first['msg']} at {'.'.join(map(str, first['loc']))}"
            )
    return unreadable


def _print(report: Report) -> None:
    for name, count in report.counts.items():
        if count:
            print(f"  {name}: {count}")
    print(f"total: {report.left}")


async def rewrite_all(db: AsyncIOMotorDatabase, *, apply: bool) -> None:
    """Rewrite (or, without apply, count) every old value, printing the counts."""
    _print(await rewrite(db, apply=apply))
    if not apply:
        print("\ndry run: nothing written. Re-run with --apply to rewrite.")


async def verify_all(db: AsyncIOMotorDatabase) -> int:
    """Print what is left and every entry the build cannot read; 1 while either is non-empty."""
    report = await verify(db)
    _print(report)
    unreadable = await unreadable_entries(db)
    for line in unreadable:
        print(f"  UNREADABLE {line}")
    print(f"unreadable entries: {len(unreadable)}")
    return 1 if report.left or unreadable else 0


async def _run(args: argparse.Namespace) -> int:
    db = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    if args.verify:
        return await verify_all(db)
    await rewrite_all(db, apply=args.apply)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the changes")
    mode.add_argument("--verify", action="store_true", help="exit 1 while any old value is left")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
