"""Expire every approval a parked handoff (per-user MCP) subagent is waiting on.

The handoff subagent and the code that rebuilt it to resume are removed, so a
record parked by one can never resume. Left as it is, a later decision or the
timeout sweep would try to rebuild a subagent that no longer exists.

Each still-pending record is closed as timed out, its resume recipe is cleared
so no sweep retries it, and its approval card is settled as timed out in the
stored conversation. A record that was already decided but never resumed keeps
its decision and only has its recipe cleared: the HIL API has no transition out
of a decided status, so it is reported for a person to follow up.

Dry run by default; ``--apply`` writes. Run before deploying the code that
removed the handoff path.

    cd apps/api && uv run python scripts/expire_parked_handoff_subagents.py [--apply]
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.db.repositories.hil import hil_approval_repository
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.services.hil.approvals_store import clear_resume_item, mark_decided
from app.services.hil.bridge import publish_decision

#: The retired ``SubagentKind.MCP`` value a handoff subagent's resume recipe carries.
HANDOFF_SUBAGENT_KIND = "mcp"
EXPIRED_FEEDBACK = "This approval expired. Ask again."


async def parked_handoff_records() -> list[HILApprovalRecord]:
    """Every approval a handoff subagent parked on that no decision has resumed yet."""
    collection = get_async_collection(hil_approval_repository.collection_name)
    cursor = collection.find(
        {"subagent_resume.kind": HANDOFF_SUBAGENT_KIND, "resumed_at": None},
        sort=[("created_at", 1)],
    )
    return [HILApprovalRecord.model_validate(doc) async for doc in cursor]


async def expire(record: HILApprovalRecord) -> bool:
    """Close one pending record as timed out and settle its card; False when it was decided meanwhile."""
    if not await mark_decided(
        record.approval_id,
        HILApprovalStatus.TIMEOUT,
        feedback=EXPIRED_FEEDBACK,
        scope="once",
        decided_by=None,
    ):
        return False
    await clear_resume_item(record.approval_id)
    # No live stream follows a parked run's card; what reaches the user is the
    # persisted frame publish_decision settles in the stored conversation.
    await publish_decision(
        record, HILApprovalStatus.TIMEOUT, stream_id=record.stream_id, feedback=EXPIRED_FEEDBACK
    )
    return True


async def main(apply: bool) -> None:
    records = await parked_handoff_records()
    pending = [r for r in records if r.status is HILApprovalStatus.PENDING]
    decided = [r for r in records if r.status is not HILApprovalStatus.PENDING]
    print(
        f"parked handoff approvals: {len(records)} ({len(pending)} pending, {len(decided)} decided)"
    )
    for record in decided:
        print(
            f"  DECIDED, NEVER RESUMED  {record.approval_id} ({record.status.value}, "
            f"tool {record.tool_name}, conversation {record.conversation_id}): the action "
            "did not run; tell the user to ask again"
        )
    if not apply:
        print("dry run: pass --apply to expire them")
        return

    expired = 0
    for record in pending:
        if await expire(record):
            expired += 1
        else:
            print(f"  SKIPPED {record.approval_id}: decided while this ran; rerun to clear it")
    for record in decided:
        await clear_resume_item(record.approval_id)
    print(f"expired {expired} pending approvals, cleared {len(decided)} decided ones")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
