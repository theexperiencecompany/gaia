#!/usr/bin/env python3
"""Rewrite stored approvals into ApprovalOutcome / ApprovalDecider / ActionResult.

Four stores spoke their own words for how an approval ended: the ledger's
``state``, the approval record's ``status``, the log entry's ``decision`` and the
card payload's ``data.status``. Each old value becomes the outcome, who decided
and what the action did (the module's maps), and the old field is unset.
Dry run by default. Safe to re-run: every write matches only an old field.

Run after the conversation-entries cutover's final pass, while the old build is
fenced, then deploy: --apply, then --verify (exits 1 while any old value is left).

Usage::

    cd apps/api
    uv run python -m app.scripts.migrate_approval_vocabulary            # report only
    uv run python -m app.scripts.migrate_approval_vocabulary --apply
    uv run python -m app.scripts.migrate_approval_vocabulary --verify
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.settings import settings
from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.models.conversation_log_models import EntryKind
from shared.py.analytics.catalog.hil import ActionResult, ApprovalDecider, ApprovalOutcome

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


@dataclass
class Report:
    """How many stored documents still carry, or were moved off, each old value."""

    counts: dict[str, int] = field(default_factory=dict)

    @property
    def left(self) -> int:
        """Return how many old values the report counted."""
        return sum(self.counts.values())


def _card_filter(status: str) -> dict[str, object]:
    return {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data.status": status}


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
        }
    )


def _print(report: Report) -> None:
    for name, count in report.counts.items():
        if count:
            print(f"  {name}: {count}")
    print(f"total: {report.left}")


async def _run(args: argparse.Namespace) -> int:
    db = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    if args.verify:
        report = await verify(db)
        _print(report)
        return 1 if report.left else 0
    _print(await rewrite(db, apply=args.apply))
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply to rewrite.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the changes")
    mode.add_argument("--verify", action="store_true", help="exit 1 while any old value is left")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
