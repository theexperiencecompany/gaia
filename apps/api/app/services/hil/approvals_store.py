"""Durable persistence for HIL approval records (Mongo ``hil_approvals``).

The decision source of truth. A pending record is written when the gate asks for
approval and transitioned to a terminal status exactly once when a decision
arrives — the one-time guarantee is a conditional ``pending -> decided`` update,
so a duplicate or racing decision cannot double-resolve the same request.

Writes are idempotent because the gate's pre-``interrupt()`` code re-runs from the
top of the node on every resume replay: the id is derived from the tool call
(:func:`approval_id_for`) and creation is an upsert, so a replay neither creates a
second record nor resets a decided one.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.db.mongodb.collections import hil_approvals_collection
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus


def approval_id_for(conversation_id: str, tool_call_id: str) -> str:
    """Deterministic approval id for one gated tool call.

    Derived rather than random: the node re-runs from the top on resume, so a
    ``uuid4()`` here would mint a second id (and a second card) on every replay.
    ``tool_call_id`` is stable across replays — it lives in the checkpointed
    AI message.
    """
    return str(uuid5(NAMESPACE_URL, f"hil:{conversation_id}:{tool_call_id}"))


async def upsert_pending_approval(
    *,
    approval_id: str,
    user_id: str,
    conversation_id: str,
    stream_id: str,
    tool_name: str,
    tool_call_id: str,
    args: dict[str, Any],
    summary: str,
    integration_name: str | None,
) -> bool:
    """Create the pending record if absent. Returns ``True`` only when newly created.

    ``$setOnInsert`` so a resume replay never resurrects a decided record. The
    return value is what the caller uses to publish the approval card exactly
    once (a replay must not re-publish it).
    """
    now = datetime.now(UTC)
    record = HILApprovalRecord(
        approval_id=approval_id,
        user_id=user_id,
        conversation_id=conversation_id,
        stream_id=stream_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args=args,
        summary=summary,
        integration_name=integration_name,
        created_at=now,
        expires_at=now + timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS),
    )
    doc = record.model_dump()
    doc["_id"] = approval_id
    result = await hil_approvals_collection.update_one(
        {"_id": approval_id}, {"$setOnInsert": doc}, upsert=True
    )
    return result.upserted_id is not None


async def record_auto_approval(
    *,
    approval_id: str,
    user_id: str,
    conversation_id: str,
    stream_id: str,
    tool_name: str,
    tool_call_id: str,
    args: dict[str, Any],
    summary: str,
    integration_name: str | None,
    reason: str,
) -> None:
    """Log an action auto mode ran without asking — the receipt behind its card.

    Written already-decided (never ``pending``), so it is a record, not a request: no
    sweep expires it and no decision endpoint can resolve it. ``$setOnInsert`` keeps it
    idempotent for the same reason the pending upsert is.
    """
    now = datetime.now(UTC)
    record = HILApprovalRecord(
        approval_id=approval_id,
        user_id=user_id,
        conversation_id=conversation_id,
        stream_id=stream_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args=args,
        summary=summary,
        integration_name=integration_name,
        status="auto_approved",
        auto_reason=reason,
        decided_at=now,
        created_at=now,
        expires_at=now,
    )
    doc = record.model_dump()
    doc["_id"] = approval_id
    await hil_approvals_collection.update_one(
        {"_id": approval_id}, {"$setOnInsert": doc}, upsert=True
    )


def _hydrate(doc: dict[str, Any]) -> HILApprovalRecord:
    doc.pop("_id", None)
    return HILApprovalRecord(**doc)


async def get_approval(approval_id: str) -> HILApprovalRecord | None:
    """Load one approval record, or ``None`` when it does not exist."""
    doc = await hil_approvals_collection.find_one({"_id": approval_id})
    return _hydrate(doc) if doc else None


async def mark_decided(
    approval_id: str,
    status: HILApprovalStatus,
    *,
    feedback: str | None,
    scope: str,
    decided_by: str | None,
) -> bool:
    """Transition a ``pending`` record to a terminal status, exactly once.

    Returns ``True`` if this call performed the transition, ``False`` if the
    record was missing or already decided — the caller uses this to enforce
    one-time resolution before resuming the paused run.
    """
    result = await hil_approvals_collection.update_one(
        {"_id": approval_id, "status": "pending"},
        {
            "$set": {
                "status": status,
                "feedback": feedback,
                "scope": scope,
                "decided_by": decided_by,
                "decided_at": datetime.now(UTC),
            }
        },
    )
    return result.modified_count == 1


async def set_resume_item(approval_id: str, item: dict[str, Any]) -> None:
    """Attach the paused run's re-dispatch context to its approval record."""
    await hil_approvals_collection.update_one({"_id": approval_id}, {"$set": {"resume_item": item}})


async def stamp_subagent_resume(
    approval_id: str, *, subagent_thread_id: str, subagent_agent_name: str
) -> None:
    """Record the parked background subagent's checkpoint thread on its approval.

    The durable link the ``wait_for_subagents`` join uses to rediscover and resume this
    subagent after the executor's own pause — the deterministic thread id survives the
    resume where the in-process session does not.
    """
    await hil_approvals_collection.update_one(
        {"_id": approval_id},
        {
            "$set": {
                "subagent_thread_id": subagent_thread_id,
                "subagent_agent_name": subagent_agent_name,
            }
        },
    )


async def list_parked_subagents_for_conversation(conversation_id: str) -> list[HILApprovalRecord]:
    """A conversation's background-subagent approvals — the join's work list.

    Records stamped with a ``subagent_thread_id`` (a detached subagent parked on them)
    whose subagent has not yet been collected — ``pending`` (still awaiting a decision)
    or decided (ready to resume). Filtered on ``subagent_collected_at``, NOT
    ``resumed_at``: the latter records executor re-dispatch, which happens on the first
    decision while other batch members are still uncollected. Conversation-scoped
    because the executor busy lock guarantees one run per conversation; ``stream_id``
    cannot be used — it changes on resume.
    """
    cursor = hil_approvals_collection.find(
        {
            "conversation_id": conversation_id,
            "subagent_thread_id": {"$ne": None},
            "subagent_collected_at": None,
        }
    ).sort("created_at", 1)
    return [_hydrate(doc) async for doc in cursor]


async def mark_subagent_collected(approval_id: str) -> None:
    """Stamp that the join resumed this parked subagent and collected its result."""
    await hil_approvals_collection.update_one(
        {"_id": approval_id}, {"$set": {"subagent_collected_at": datetime.now(UTC)}}
    )


async def mark_resumed(approval_id: str) -> None:
    """Stamp that the decided run was re-dispatched (sweep skips it)."""
    await hil_approvals_collection.update_one(
        {"_id": approval_id}, {"$set": {"resumed_at": datetime.now(UTC)}}
    )


async def list_expired_pending() -> list[HILApprovalRecord]:
    """Pending approvals past ``expires_at`` — the timeout sweep's work list."""
    cursor = hil_approvals_collection.find(
        {"status": "pending", "expires_at": {"$lt": datetime.now(UTC)}}
    )
    return [_hydrate(doc) async for doc in cursor]


async def list_decided_unresumed(grace_seconds: float) -> list[HILApprovalRecord]:
    """Decided records whose resume never dispatched (crash between the decided
    transition and the run spawn) — the sweep re-dispatches them."""
    cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
    cursor = hil_approvals_collection.find(
        {
            "status": {"$in": ["approved", "denied", "abandoned"]},
            "resumed_at": None,
            "resume_item": {"$ne": None},
            "decided_at": {"$lt": cutoff},
        }
    )
    return [_hydrate(doc) async for doc in cursor]


async def list_pending_for_conversation(conversation_id: str) -> list[HILApprovalRecord]:
    """Every still-pending approval in a conversation, oldest first."""
    cursor = hil_approvals_collection.find(
        {"conversation_id": conversation_id, "status": "pending"}
    ).sort("created_at", 1)
    return [_hydrate(doc) async for doc in cursor]
