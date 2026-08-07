"""Repositories for the HIL collections — approval records and tool-risk cache.

``hil_approvals`` is keyed by the deterministic ``approval_id`` stored as the
string ``_id`` (see ``approval_id_for``): the gate's pre-``interrupt()`` code
re-runs from the top of the node on every resume replay, and the unique ``_id``
is what makes record creation naturally once-only — a replay's duplicate insert
is the idempotency guarantee working, not an error.

Uncached (``cache_policy = None``): approvals are decision state read at
low volume around pauses, and the pending → decided transition is a conditional
write the entity cache could only misrepresent.
"""

from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.hil_models import (
    HILApprovalRecord,
    HILApprovalStatus,
    HILApprovalUpdate,
    HILToolRiskRecord,
    HILToolRiskUpdate,
)


class HilApprovalRepository(MongoRepository[HILApprovalRecord, HILApprovalUpdate]):
    collection_name = "hil_approvals"
    document_model = HILApprovalRecord
    update_model = HILApprovalUpdate
    uses_object_id = False
    cache_policy = None

    async def create_if_absent(self, record: HILApprovalRecord) -> bool:
        """Insert the record unless its ``approval_id`` already exists.

        Returns ``True`` only when newly created — the caller publishes the
        approval card exactly once on that signal. A duplicate id is a resume
        replay re-running the gate's pre-pause code: the existing record (pending
        or already decided) must never be reset, so the duplicate is a no-op.
        """
        doc = record.model_copy(update={"id": record.approval_id})
        try:
            await self.create(doc)
        except DuplicateKeyError:
            return False
        return True

    async def mark_decided(
        self,
        approval_id: str,
        status: HILApprovalStatus,
        *,
        feedback: str | None,
        scope: str,
        decided_by: str | None,
    ) -> bool:
        """Transition a ``pending`` record to a terminal status, exactly once.

        Conditional on the current status so a duplicate or racing decision
        cannot double-resolve: only the call that performed the transition
        returns ``True``.
        """
        updated = await self._apply_raw_update(
            {"_id": approval_id, "status": HILApprovalStatus.PENDING},
            {
                "$set": {
                    "status": status,
                    "feedback": feedback,
                    "scope": scope,
                    "decided_by": decided_by,
                    "decided_at": datetime.now(UTC),
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    async def list_parked_subagents_for_conversation(
        self, conversation_id: str
    ) -> list[HILApprovalRecord]:
        """Records a detached background subagent parked on, oldest first,
        that the ``wait_for_subagents`` join has not yet collected."""
        return await self._find(
            {
                "conversation_id": conversation_id,
                "subagent_thread_id": {"$ne": None},
                "subagent_collected_at": None,
            },
            sort=[("created_at", 1)],
        )

    async def list_expired_pending(self) -> list[HILApprovalRecord]:
        """Pending approvals past ``expires_at`` — the timeout sweep's work list."""
        return await self._find(
            {"status": HILApprovalStatus.PENDING, "expires_at": {"$lt": datetime.now(UTC)}}
        )

    async def list_decided_unresumed(
        self, statuses: list[str], grace_seconds: float
    ) -> list[HILApprovalRecord]:
        """Decided records whose resume never dispatched (crash between the
        decided transition and the run spawn) — the sweep re-dispatches them."""
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        return await self._find(
            {
                "status": {"$in": statuses},
                "resumed_at": None,
                "resume_item": {"$ne": None},
                "decided_at": {"$lt": cutoff},
            }
        )

    async def list_pending_for_conversation(self, conversation_id: str) -> list[HILApprovalRecord]:
        """Every still-pending approval in a conversation, oldest first."""
        return await self._find(
            {"conversation_id": conversation_id, "status": HILApprovalStatus.PENDING},
            sort=[("created_at", 1)],
        )


class HilToolRiskRepository(MongoRepository[HILToolRiskRecord, HILToolRiskUpdate]):
    collection_name = "hil_tool_risk"
    document_model = HILToolRiskRecord
    update_model = HILToolRiskUpdate
    uses_object_id = True
    cache_policy = None

    async def find_classification(
        self, tool_name: str, description_hash: str
    ) -> HILToolRiskRecord | None:
        """The stored verdict for this exact tool+description, or ``None``."""
        return await self._find_one({"tool_name": tool_name, "description_hash": description_hash})

    async def upsert_classification(self, record: HILToolRiskRecord) -> None:
        """Store (or refresh) the verdict, keyed by tool+description.

        An upsert on the business key rather than ``create``: a changed
        description re-classifies and must overwrite the old verdict in place.
        """
        await self._raw_collection().update_one(
            {"tool_name": record.tool_name, "description_hash": record.description_hash},
            {"$set": record.model_dump(exclude={"id"})},
            upsert=True,
        )


hil_approval_repository = HilApprovalRepository()
hil_tool_risk_repository = HilToolRiskRepository()
