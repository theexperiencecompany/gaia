"""Repository for the executor-free approval ledger (approval_ledger collection).

One row per gated call envelope. Uncached (cache_policy = None): rows are
decision state read at low volume, and every transition is a conditional write
the entity cache could only misrepresent. A pending row leaves by the decision the
conversation log took for it, and delivering_since leases that decision's hand-off.

Dedup is atomic: a partial unique index on (conversation_id, fingerprint)
over live states makes the second concurrent insert fail, and the loser reads
the winner's id. Query-first alone would double-insert under races and an
approve-all would double-execute.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.hil_models import ApprovalLedgerDocument, ApprovalProposal
from shared.py.approvals import ActionResult, ApprovalOutcome

#: The unique index that dedups live rows by (conversation_id, fingerprint).
LIVE_ROW_INDEX_NAME = "conv_fingerprint_open_unique"
#: Rows that still hold their call (ApprovalLedgerDocument.live); also that index's filter.
LIVE_ROW_FILTER: dict[str, Any] = {
    "$or": [
        {"outcome": {"$type": "null"}},
        {"outcome": ApprovalOutcome.APPROVED.value, "action": {"$type": "null"}},
    ]
}


def new_approval_id() -> str:
    """Return a fresh approval id: the log asks under it before the ledger holds its row."""
    return f"ap_{uuid4().hex[:12]}"


class ApprovalLedgerRepository(MongoRepository[ApprovalLedgerDocument, ApprovalLedgerDocument]):
    collection_name = "approval_ledger"
    document_model = ApprovalLedgerDocument
    update_model = ApprovalLedgerDocument
    uses_object_id = True
    cache_policy = None

    async def register(self, proposal: ApprovalProposal, approval_id: str) -> str:
        """Insert a PENDING row under approval_id, or return the live duplicate's id.

        Dedup consults live states only: a terminal fingerprint re-registers
        fresh (revoked-then-reproposed must not collapse into a dead id).
        The loser's read-after-conflict is what makes concurrent proposes
        converge on one id instead of double-executing on approve-all.
        """
        existing = await self.find_live(proposal.fingerprint, proposal.conversation_id)
        if existing is not None:
            return existing.approval_id
        row = ApprovalLedgerDocument(
            approval_id=approval_id, created_at=datetime.now(UTC), **proposal.model_dump()
        )
        try:
            # Written with its nulls, not through create(): the live unique index finds an
            # undecided row by its null outcome, and a missing field would escape it.
            await self._raw_collection().insert_one(row.model_dump(exclude={"id"}))
        except DuplicateKeyError:
            # Lost the insert race (partial unique index on live
            # conversation+fingerprint): the winner's row is the id.
            winner = await self.find_live(proposal.fingerprint, proposal.conversation_id)
            if winner is not None:
                return winner.approval_id
            raise
        return approval_id

    async def claim_delivery(
        self, approval_id: str, now: datetime, lease: timedelta
    ) -> ApprovalLedgerDocument | None:
        """Take the one hand-off of this approval's decision, returning the row; None when it is not ours to make.

        Ours while the row is pending with no hand-off under way, or when the last one began
        longer than lease ago and never finished. A settled row with none under way was handed off.
        """
        raw = await self._raw_collection().find_one_and_update(
            {
                "approval_id": approval_id,
                "$or": [
                    {"outcome": {"$type": "null"}, "delivering_since": {"$type": "null"}},
                    {"delivering_since": {"$lt": now - lease}},
                ],
            },
            {"$set": {"delivering_since": now}},
            return_document=ReturnDocument.AFTER,
        )
        return ApprovalLedgerDocument.model_validate(raw) if raw else None

    async def finish_delivery(self, approval_id: str, since: datetime) -> None:
        """End the hand-off begun at since; a later one that took over keeps its own."""
        await self._raw_collection().update_one(
            {"approval_id": approval_id, "delivering_since": since},
            {"$set": {"delivering_since": None}},
        )

    async def list_stale_deliveries(self, cutoff: datetime) -> list[ApprovalLedgerDocument]:
        """List rows whose hand-off began before cutoff and never finished, oldest first."""
        cursor = (
            self._raw_collection()
            .find({"delivering_since": {"$lt": cutoff}})
            .sort("delivering_since", 1)
        )
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=200)
        ]

    async def settle(
        self,
        approval_id: str,
        outcome: ApprovalOutcome,
        *,
        decided_by: str | None = None,
        feedback: str | None = None,
    ) -> bool:
        """Give a pending row its outcome, exactly once.

        Concurrent contenders race on the pending filter and one wins; the row version
        bumps for stale clients. A decision stamp rides in the same write as decided_at.
        """
        update: dict[str, object] = {"outcome": outcome.value}
        if decided_by is not None:
            update["decided_by"] = decided_by
        if feedback is not None:
            update["feedback"] = feedback
        if decided_by is not None or feedback is not None:
            update["decided_at"] = datetime.now(UTC)
        result = await self._raw_collection().update_one(
            {"approval_id": approval_id, "outcome": {"$type": "null"}},
            {"$set": update, "$inc": {"v": 1}},
        )
        return bool(result.modified_count)

    async def finish_action(self, approval_id: str, result: ActionResult) -> bool:
        """Record what an executing action came to, exactly once."""
        update = await self._raw_collection().update_one(
            {"approval_id": approval_id, "action": ActionResult.EXECUTING.value},
            {"$set": {"action": result.value}, "$inc": {"v": 1}},
        )
        return bool(update.modified_count)

    async def claim_executing(self, approval_id: str) -> bool:
        """Start an approved row's action and stamp the claim time, atomically.

        Exactly one claimant wins per id; the timestamp lets the lazy
        reconciler tell "provider call in flight" from "process died holding
        the claim". Called only after acquiring the execution semaphore, so a
        row whose action is executing always means work actually started.
        """
        result = await self._raw_collection().update_one(
            {
                "approval_id": approval_id,
                "outcome": ApprovalOutcome.APPROVED.value,
                "action": {"$type": "null"},
            },
            {
                "$set": {
                    "action": ActionResult.EXECUTING.value,
                    "executing_started_at": datetime.now(UTC),
                },
                "$inc": {"v": 1},
            },
        )
        return bool(result.modified_count)

    async def list_stalled_executing(
        self, cutoff: datetime, conversation_id: str | None = None
    ) -> list[ApprovalLedgerDocument]:
        """List rows still executing whose claim predates the cutoff (presumed crashed).

        Scoped to one conversation when given: the reconciler heals its own
        conversation per decide, and a global scan on every tap scales with
        every conversation's stalls, not this one's.
        """
        query: dict[str, Any] = {
            "action": ActionResult.EXECUTING.value,
            "executing_started_at": {"$lt": cutoff},
        }
        if conversation_id is not None:
            query["conversation_id"] = conversation_id
        cursor = self._raw_collection().find(query).sort("executing_started_at", 1)
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=200)
        ]

    async def get_by_approval_id(self, approval_id: str) -> ApprovalLedgerDocument | None:
        """Return one row by its ap_ id, or None."""
        raw = await self._raw_collection().find_one({"approval_id": approval_id})
        return ApprovalLedgerDocument.model_validate(raw) if raw else None

    async def find_live(
        self, fingerprint: str, conversation_id: str
    ) -> ApprovalLedgerDocument | None:
        """Return the newest live row for a fingerprint, or None.

        The state predicate rides in the query so the partial live index
        applies and terminal rows never even load — instead of fetching 50
        rows and filtering in Python.
        """
        cursor = (
            self._raw_collection()
            .find(
                {"fingerprint": fingerprint, "conversation_id": conversation_id, **LIVE_ROW_FILTER}
            )
            .sort("created_at", -1)
        )
        raws = await cursor.to_list(length=50)
        for raw in raws:
            doc = ApprovalLedgerDocument.model_validate(raw)
            if doc.live:
                return doc
        return None

    async def find_latest_denied(
        self, fingerprint: str, conversation_id: str
    ) -> ApprovalLedgerDocument | None:
        """Return the newest denied row for reject-memory context, or None."""
        raw = await self._raw_collection().find_one(
            {
                "fingerprint": fingerprint,
                "conversation_id": conversation_id,
                "outcome": ApprovalOutcome.DENIED.value,
            },
            sort=[("created_at", -1)],
        )
        return ApprovalLedgerDocument.model_validate(raw) if raw else None

    async def find_amended(
        self, approval_id: str, conversation_id: str
    ) -> ApprovalLedgerDocument | None:
        """Return the conversation's row a redo names, when the user approved it with a change.

        That stored call never runs; the redo call carries its id, which is the only link.
        """
        raw = await self._raw_collection().find_one(
            {"approval_id": approval_id, "conversation_id": conversation_id}
        )
        if raw is None:
            return None
        row = ApprovalLedgerDocument.model_validate(raw)
        amended = (
            row.outcome is ApprovalOutcome.APPROVED
            and row.feedback is not None
            and row.action is None
        )
        return row if amended else None

    async def list_by_owners(
        self, owner_run_type: str, owner_ids: list[str], *, created_since: datetime
    ) -> list[ApprovalLedgerDocument]:
        """Rows background owners registered since created_since, oldest first.

        Batch read for list views (one query per page, not per row). Whether one still
        waits is the conversation log's to say, not the row's.
        """
        if not owner_run_type or not owner_ids:
            return []
        cursor = (
            self._raw_collection()
            .find(
                {
                    "owner_run_type": owner_run_type,
                    "owner_id": {"$in": owner_ids},
                    "created_at": {"$gte": created_since},
                }
            )
            .sort("created_at", 1)
        )
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=200)
        ]

    async def list_by_tasks(
        self, task_ids: list[str], *, created_since: datetime
    ) -> list[ApprovalLedgerDocument]:
        """Rows these GAIA tasks' runs registered since created_since, oldest first; the log says which wait."""
        if not task_ids:
            return []
        cursor = (
            self._raw_collection()
            .find({"owner_task_id": {"$in": task_ids}, "created_at": {"$gte": created_since}})
            .sort("created_at", 1)
        )
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=200)
        ]

    async def recent_tool_outcomes(
        self, user_id: str, tool_name: str, *, limit: int = 10, since_days: int = 30
    ) -> list[ApprovalLedgerDocument]:
        """Newest decided rows for one user's tool — auto mode's memory.

        Only rows with a decision timestamp: pendings were never answered, so
        they are not votes for or against anything.
        """
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        cursor = (
            self._raw_collection()
            .find(
                {
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "decided_at": {"$gte": cutoff},
                }
            )
            .sort("decided_at", -1)
        )
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=limit)
        ]


approval_ledger_repository = ApprovalLedgerRepository()
