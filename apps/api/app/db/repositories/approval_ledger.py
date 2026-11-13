"""Repository for the executor-free approval ledger (approval_ledger collection).

One row per gated call envelope. Uncached (cache_policy = None): rows are
decision state read at low volume, and every transition is a conditional write
the entity cache could only misrepresent. Rows never expire — a pending row
leaves only by user decision or agent revoke.

Dedup is atomic: a partial unique index on (conversation_id, fingerprint)
over live states makes the second concurrent insert fail, and the loser reads
the winner's id. Query-first alone would double-insert under races and an
approve-all would double-execute.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.hil_models import (
    LIVE_LEDGER_STATES,
    ApprovalLedgerDocument,
    ApprovalProposal,
    LedgerState,
)


class ApprovalLedgerRepository(MongoRepository[ApprovalLedgerDocument, ApprovalLedgerDocument]):
    collection_name = "approval_ledger"
    document_model = ApprovalLedgerDocument
    update_model = ApprovalLedgerDocument
    uses_object_id = True
    cache_policy = None

    async def register(self, proposal: ApprovalProposal) -> str:
        """Insert a PENDING row for the proposal, or return the live duplicate's id.

        Dedup consults live states only: a terminal fingerprint re-registers
        fresh (revoked-then-reproposed must not collapse into a dead id).
        The loser's read-after-conflict is what makes concurrent proposes
        converge on one id instead of double-executing on approve-all.
        """
        existing = await self.find_live(proposal.fingerprint, proposal.conversation_id)
        if existing is not None:
            return existing.approval_id
        approval_id = f"ap_{uuid4().hex[:12]}"
        try:
            await self.create(
                ApprovalLedgerDocument(approval_id=approval_id, **proposal.model_dump())
            )
        except DuplicateKeyError:
            # Lost the insert race (partial unique index on live
            # conversation+fingerprint): the winner's row is the id.
            winner = await self.find_live(proposal.fingerprint, proposal.conversation_id)
            if winner is not None:
                return winner.approval_id
            raise
        return approval_id

    async def claim_resume(self, approval_id: str) -> bool:
        """Claim the one resume this approval may trigger; exactly one winner.

        A retried tap, a reconnect replay, and a racing worker converge here,
        and only the winner re-enqueues the owner. A resumed owner that gates
        again registers a fresh approval with its own claim, so no counter is
        needed — every resume costs a new human tap.
        """
        result = await self._raw_collection().update_one(
            {"approval_id": approval_id, "owner_resumed": False},
            {"$set": {"owner_resumed": True}},
        )
        return bool(result.modified_count)

    async def transition(
        self,
        approval_id: str,
        expected: LedgerState,
        nxt: LedgerState,
        *,
        decided_by: str | None = None,
        feedback: str | None = None,
    ) -> bool:
        """Move one row from expected to nxt, exactly once.

        The CAS behind every ledger edge: concurrent contenders race on the
        filter and exactly one wins. Bumps the row version for stale clients.
        A decision stamp (decided_by and/or feedback) rides in the same write
        as decided_at, so a committed row is never stamp-less.
        """
        update: dict[str, object] = {"state": str(nxt)}
        if decided_by is not None:
            update["decided_by"] = decided_by
        if feedback is not None:
            update["feedback"] = feedback
        if decided_by is not None or feedback is not None:
            update["decided_at"] = datetime.now(UTC)
        result = await self._raw_collection().update_one(
            {"approval_id": approval_id, "state": str(expected)},
            {"$set": update, "$inc": {"v": 1}},
        )
        return bool(result.modified_count)

    async def claim_executing(self, approval_id: str) -> bool:
        """Move APPROVED -> EXECUTING and stamp the claim time, atomically.

        Exactly one claimant wins per id; the timestamp lets the lazy
        reconciler tell "provider call in flight" from "process died holding
        the claim". Called only after acquiring the execution semaphore, so a
        row in EXECUTING always means work actually started.
        """
        result = await self._raw_collection().update_one(
            {"approval_id": approval_id, "state": str(LedgerState.APPROVED)},
            {
                "$set": {
                    "state": str(LedgerState.EXECUTING),
                    "executing_started_at": datetime.now(UTC),
                },
                "$inc": {"v": 1},
            },
        )
        return bool(result.modified_count)

    async def list_stalled_executing(
        self, cutoff: datetime, conversation_id: str | None = None
    ) -> list[ApprovalLedgerDocument]:
        """List EXECUTING rows whose claim predates the cutoff (presumed crashed).

        Scoped to one conversation when given: the reconciler heals its own
        conversation per decide, and a global scan on every tap scales with
        every conversation's stalls, not this one's.
        """
        query: dict[str, Any] = {
            "state": str(LedgerState.EXECUTING),
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
        """Return the newest live (PENDING/APPROVED) row for a fingerprint, or None.

        The state predicate rides in the query so the partial live index
        applies and terminal rows never even load — instead of fetching 50
        rows and filtering in Python.
        """
        cursor = (
            self._raw_collection()
            .find(
                {
                    "fingerprint": fingerprint,
                    "conversation_id": conversation_id,
                    "state": {"$in": sorted(str(s) for s in LIVE_LEDGER_STATES)},
                }
            )
            .sort("created_at", -1)
        )
        raws = await cursor.to_list(length=50)
        for raw in raws:
            doc = ApprovalLedgerDocument.model_validate(raw)
            if doc.state in LIVE_LEDGER_STATES:
                return doc
        return None

    async def list_open(self, conversation_id: str) -> list[ApprovalLedgerDocument]:
        """Live rows for a conversation, oldest first (registration order)."""
        cursor = (
            self._raw_collection()
            .find(
                {
                    "conversation_id": conversation_id,
                    "state": {"$in": sorted(str(s) for s in LIVE_LEDGER_STATES)},
                }
            )
            .sort("created_at", 1)
        )
        return [
            ApprovalLedgerDocument.model_validate(raw) for raw in await cursor.to_list(length=200)
        ]

    async def find_latest_denied(
        self, fingerprint: str, conversation_id: str
    ) -> ApprovalLedgerDocument | None:
        """Return the newest DENIED row for reject-memory context, or None."""
        raw = await self._raw_collection().find_one(
            {
                "fingerprint": fingerprint,
                "conversation_id": conversation_id,
                "state": str(LedgerState.DENIED),
            },
            sort=[("created_at", -1)],
        )
        return ApprovalLedgerDocument.model_validate(raw) if raw else None

    async def list_live_by_owners(
        self, owner_run_type: str, owner_ids: list[str]
    ) -> list[ApprovalLedgerDocument]:
        """Live (PENDING/APPROVED) rows parked by background owners, oldest first.

        Batch read for list views (one query per page, not per row). Terminal
        rows never match — a decided owner has nothing waiting.
        """
        if not owner_run_type or not owner_ids:
            return []
        cursor = (
            self._raw_collection()
            .find(
                {
                    "owner_run_type": owner_run_type,
                    "owner_id": {"$in": owner_ids},
                    "state": {"$in": sorted(str(s) for s in LIVE_LEDGER_STATES)},
                }
            )
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
