"""Apply a HIL decision and resume the executor run it paused.

The single entry point for every decision source — approval buttons, a bot's
interactive component, the conversational resolver, and the timeout sweep. Each
supplies a DecisionKind; everything else is identical.

Two guarantees:

* **Exactly once.** The pending -> decided transition is a conditional Mongo
  update. A double click, a racing bot callback, and a sweep firing against an
  approval the user just answered all lose the race and resolve nothing.
* **The run always continues.** Whatever the decision, the paused thread is
  re-dispatched so it either performs the action or tells the model it was
  refused. A resolved approval that never resumed would strand the conversation's
  executor lock until its TTL.
"""

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Literal, TypedDict, cast

from langgraph.types import Command

from app.agents.core.background.executor_queue import (
    ExecutorRunItem,
    LockClaim,
    prepare_run_from_item,
)
from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.subagents.parked_resume import resume_parked_subagent
from app.constants.hil import (
    HIL_DECIDED_UNRESUMED_GRACE_SECONDS,
)
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.schemas.hil_schemas import BatchDecisionOutcome
from app.services.hil.approvals_store import (
    clear_resume_item,
    get_approval,
    list_decided_unresumed,
    list_expired_pending,
    list_pending_for_conversation,
    mark_decided,
    mark_resumed,
)
from app.services.hil.bridge import publish_decision
from app.services.hil.resume_slot import claim_resume_dispatch, release_resume_dispatch
from app.services.latency_metrics import observe_hil_dispatch_lag, observe_hil_user_wait
from app.utils.errors import AppError
from shared.py.wide_events import log

DecisionKind = Literal["approve", "deny", "timeout", "abandon"]


class SweepCounts(TypedDict):
    """One approval-sweep pass: expired timeouts and redispatched resumes."""

    expired: int
    redispatched: int


# Recorded on approvals closed because the user cancelled the run that parked on them.
# No run ever reads it back (there is nothing left to resume) — it is the audit trail.
CANCELLED_FEEDBACK = "The user cancelled this task; the action was never performed."

# What the record audits. The paused gate receives the same status, except
# "abandoned" resumes as a denial — the user moved on, the agent must not act.
_TERMINAL_STATUS: dict[str, HILApprovalStatus] = {
    "approve": HILApprovalStatus.APPROVED,
    "deny": HILApprovalStatus.DENIED,
    "timeout": HILApprovalStatus.TIMEOUT,
    "abandon": HILApprovalStatus.ABANDONED,
}

# Prevent GC of resume tasks spawned here (create_task keeps only a weak ref).
_resume_tasks: set[asyncio.Task[None]] = set()


class ApprovalRequestNotFoundError(AppError):
    """Raised (410) when an approval request has expired or was already resolved."""

    def __init__(self) -> None:
        super().__init__(
            message="Approval request expired or already resolved",
            status_code=HTTPStatus.GONE,
        )


class ApprovalRequestForbiddenError(AppError):
    """Raised (403) when an approval request belongs to a different user."""

    def __init__(self) -> None:
        super().__init__(
            message="Approval request belongs to another user",
            status_code=HTTPStatus.FORBIDDEN,
        )


class ApprovalNotResumableError(AppError):
    """Raised (503) when the paused run's re-dispatch context is missing.

    The record stays pending — committing the decision without a resumable
    run would tell the user "approved" about an action that can never execute.
    The sweep expires the record instead.
    """

    def __init__(self) -> None:
        super().__init__(
            message="The paused task cannot be resumed; it may have failed to pause cleanly",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )


async def resolve_approval(
    *,
    approval_id: str,
    user_id: str,
    kind: DecisionKind,
    feedback: str | None = None,
    scope: str = "once",
) -> HILApprovalRecord:
    """Record the decision, then resume the run waiting on it."""
    record = await get_approval(approval_id)
    if record is None:
        raise ApprovalRequestNotFoundError()
    return await _resolve_record(record, user_id=user_id, kind=kind, feedback=feedback, scope=scope)


async def resolve_approvals_batch(
    user_id: str, decisions: list[tuple[str, DecisionKind, str | None]]
) -> list[BatchDecisionOutcome]:
    """Apply several decisions in one submission — the web batch review's backend.

    Each approval still transitions exactly once; the per-conversation resume slot
    means only the first decision actually dispatches the executor, whose replayed
    gates read the rest off their records. One failed item never blocks the others —
    its outcome is reported instead.
    """
    outcomes: list[BatchDecisionOutcome] = []
    for approval_id, kind, feedback in decisions:
        try:
            await resolve_approval(
                approval_id=approval_id, user_id=user_id, kind=kind, feedback=feedback
            )
            outcomes.append(BatchDecisionOutcome(approval_id=approval_id, resolved=True))
        except ApprovalRequestNotFoundError:
            outcomes.append(
                BatchDecisionOutcome(approval_id=approval_id, resolved=False, reason="not_found")
            )
        except ApprovalRequestForbiddenError:
            outcomes.append(
                BatchDecisionOutcome(approval_id=approval_id, resolved=False, reason="forbidden")
            )
        except ApprovalNotResumableError:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=approval_id, resolved=False, reason="not_resumable"
                )
            )
        except Exception as e:  # one item's infra failure must not strand the rest
            # The item stays pending (nothing transitioned), so the sweep retries it; the
            # rest of the batch still processes. Reported, not swallowed.
            log.error(
                f"{LogTag.HIL} Batch decision failed for",
                approval_id=approval_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            outcomes.append(
                BatchDecisionOutcome(approval_id=approval_id, resolved=False, reason="error")
            )
    return outcomes


async def abandon_conversation_approvals(
    conversation_id: str, user_id: str, feedback: str
) -> list[str]:
    """Resolve every pending approval in a conversation as abandoned.

    Used when the user moves on to an unrelated request: each paused run resumes,
    sees a refusal, wraps up, and releases the conversation's executor lock so the
    new turn's work can proceed.
    """
    abandoned: list[str] = []
    for record in await list_pending_for_conversation(conversation_id):
        try:
            await _resolve_or_close(record, user_id=user_id, kind="abandon", feedback=feedback)
            abandoned.append(record.approval_id)
        except (ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
            # Already decided, or not this user's to decide. Keep going: one record must
            # never strand the conversation's other paused runs, which is the whole point.
            continue
    return abandoned


async def cancel_conversation_approvals(conversation_id: str, user_id: str) -> list[str]:
    """Close a cancelled run's pending approvals so nothing can restart it.

    Left pending, a later "Approve" or the timeout sweep would re-dispatch the very run the
    user stopped, on a fresh stream the cancel flag doesn't cover. Deliberately does NOT
    resume (unlike abandon_conversation_approvals) since the run is already gone. mark_decided
    runs first: it is the exactly-once mutex, so only its winner may clear resume_item.
    """
    cancelled: list[str] = []
    for record in await list_pending_for_conversation(conversation_id):
        if record.user_id != user_id:
            continue
        if not await mark_decided(
            record.approval_id,
            HILApprovalStatus.ABANDONED,
            feedback=CANCELLED_FEEDBACK,
            scope="once",
            decided_by=user_id,
        ):
            continue
        await clear_resume_item(record.approval_id)
        cancelled.append(record.approval_id)
    if cancelled:
        log.info(
            f"{LogTag.HIL} Closed pending approvals for a cancelled run",
            conversation_id=conversation_id,
            approval_ids=cancelled,
        )
    return cancelled


async def _resolve_or_close(
    record: HILApprovalRecord,
    *,
    user_id: str,
    kind: DecisionKind,
    feedback: str | None,
) -> None:
    """Resolve a record, or close it in place when no run can be resumed.

    A record with no resume_item never had its pause registered (the executor died
    between publishing the card and recording how to restart it), so resolving it
    would only raise. Closing it stops it from hijacking every later message via
    the conversational resolver.
    """
    if record.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    if record.resume_item is None:
        log.warning(
            f"{LogTag.HIL} Closing approval with no resume context",
            approval_id=record.approval_id,
        )
        decided_at = datetime.now(UTC)
        await mark_decided(
            record.approval_id,
            _TERMINAL_STATUS[kind],
            feedback=feedback,
            scope="once",
            decided_by=None,
        )
        # Closed with no run to resume, but still a decision the user served.
        _observe_hil_user_wait(record.model_copy(update={"decided_at": decided_at}))
        return
    await _resolve_record(record, user_id=user_id, kind=kind, feedback=feedback)


async def _resolve_record(
    record: HILApprovalRecord,
    *,
    user_id: str,
    kind: DecisionKind,
    feedback: str | None,
    scope: str = "once",
) -> HILApprovalRecord:
    """Authorize, transition exactly once, and resume — from an already-loaded record."""
    if record.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    # An approval with feedback is conditional; the stored call carries none.
    # Same conversion as ledger and chat paths: record as denied with the note.
    if kind == "approve" and feedback is not None and feedback.strip() != "":
        kind = "deny"
    # A decision we cannot act on must fail (record stays pending for the sweep),
    # never report success for an action that will not run. A background subagent's
    # record carries its resume recipe from creation, so it is always resumable.
    if record.resume_item is None and record.subagent_resume is None:
        # An APPROVE with no run to carry it out is a false "going ahead", so fail loudly
        # and let the sweep expire it. A deny/timeout/abandon needs no run at all, since
        # its whole point is that the action does NOT happen, so it's safe to record.
        if kind == "approve":
            log.error(f"{LogTag.HIL} No resume context on record", approval_id=record.approval_id)
            # Settle the card without touching the record (stays pending for the
            # sweep timeout); a failed settle must not mask the refusal below.
            try:
                await publish_decision(
                    record,
                    HILApprovalStatus.ABANDONED,
                    stream_id=record.stream_id,
                    feedback="The paused task cannot be resumed.",
                )
            except Exception as e:
                log.error(
                    f"{LogTag.HIL} Could not settle the unresumable approval card",
                    approval_id=record.approval_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise ApprovalNotResumableError()

    decided_by = None if kind == "timeout" else user_id
    decided_at = datetime.now(UTC)
    transitioned = await mark_decided(
        record.approval_id,
        _TERMINAL_STATUS[kind],
        feedback=feedback,
        scope=scope,
        decided_by=decided_by,
    )
    if not transitioned:
        # Someone (or the sweep) already decided this one. Do not resume twice.
        raise ApprovalRequestNotFoundError()
    # The loaded record predates the transition; carry the decided image forward so
    # the resume dispatch (and the caller) see the decision, not the pending snapshot.
    record = record.model_copy(
        update={
            "status": _TERMINAL_STATUS[kind],
            "feedback": feedback,
            "scope": scope,
            "decided_by": decided_by,
            "decided_at": decided_at,
        }
    )
    _observe_hil_user_wait(record)

    log.set(hil={"approval_id": record.approval_id, "decision": kind, "tool": record.tool_name})
    if record.resume_item is None and record.subagent_resume is None:
        # An un-resumable deny/timeout/abandon closed in place: nothing to resume.
        log.info(
            f"{LogTag.HIL} Decision recorded without a resume dispatch",
            approval_id=record.approval_id,
        )
        return record
    await _dispatch_decided(record)
    return record


async def _dispatch_decided(record: HILApprovalRecord) -> None:
    """Resume whatever this decided record paused: a background subagent, or the executor."""
    if record.subagent_resume is None:
        await _dispatch_resume(record)
        return
    try:
        resumed = await resume_parked_subagent(record)
    except Exception as e:  # the decision is durable; the sweep retries the resume
        log.error(
            f"{LogTag.HIL} Could not resume the parked subagent; the sweep will retry",
            approval_id=record.approval_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return
    if not resumed:
        # Its run is still draining or a resume is already going; either one reads
        # this decision off the record (a draining run's park resumes on it).
        log.info(
            f"{LogTag.HIL} Parked subagent busy; its live run collects this decision",
            approval_id=record.approval_id,
        )
        return
    _observe_hil_dispatch_lag(record)
    await mark_resumed(record.approval_id)
    log.info(f"{LogTag.HIL} Resumed parked background subagent", approval_id=record.approval_id)


async def _dispatch_resume(record: HILApprovalRecord) -> None:
    """Re-dispatch the executor thread this approval paused.

    At most one resume runs per conversation: two decisions landing close together on a
    shared executor thread must not start concurrent LangGraph runs (checkpoint corruption),
    and the loser's decision is already durable on the record. mark_resumed stamps the
    record, so a crash before it is re-dispatched by the sweep from resume_item.
    """
    if not await claim_resume_dispatch(record.conversation_id):
        log.info(
            f"{LogTag.HIL} Resume already in flight for conversation; decision will be "
            "collected by the running round or the sweep",
            approval_id=record.approval_id,
        )
        return

    # Correct by construction (set_resume_item's only writer takes an ExecutorRunItem;
    # Mongo hands it back as a plain dict). cast rather than isinstance since
    # ExecutorRunItem is total=False, so {} is a valid empty item.
    prepared = await prepare_run_from_item(
        record.conversation_id,
        cast(ExecutorRunItem, record.resume_item or {}),
        # SEIZE: the paused run still holds this conversation's lock on purpose
        # (it is parked on the approval this decision answers), so the resume has
        # to take it over rather than wait for a conversation nobody holds.
        claim=LockClaim.SEIZE,
    )
    if prepared is None:
        log.error(f"{LogTag.HIL} Could not prepare resume run", approval_id=record.approval_id)
        await release_resume_dispatch(record.conversation_id)
        return

    resume: Command[Any] = Command(resume=record.resume_payload())
    task = asyncio.create_task(
        run_executor_background(
            run=prepared.run,
            task=prepared.task,
            configurable=prepared.configurable,
            resume=resume,
        )
    )
    _resume_tasks.add(task)
    task.add_done_callback(_resume_tasks.discard)
    # Timed at dispatch: mark_resumed's Mongo write below must not inflate the
    # decision-to-dispatch lag the resumed executor already started accruing.
    _observe_hil_dispatch_lag(record)
    await mark_resumed(record.approval_id)
    log.info(f"{LogTag.HIL} Resumed paused executor run", approval_id=record.approval_id)


def _observe_hil_user_wait(record: HILApprovalRecord) -> None:
    """Record how long the user took to decide, once per decision.

    Observed at the decision, not the dispatch: a decision that loses a batch
    resume race, has no run to resume, or fails preparation is still a wait the
    user served, and dropping it biases the histogram toward dispatched approvals.
    Missing or skewed stamps degrade to missing spans, never zero-filled.
    """
    try:
        if record.decided_at is None:
            return
        wait_s = (record.decided_at - record.created_at).total_seconds()
    except TypeError:  # naive/aware mix — not a measurement
        return
    if wait_s < 0.0:  # clock skew between the decider and this worker
        return
    observe_hil_user_wait(wait_s)
    log.set(hil={"user_wait_s": round(wait_s, 2)})


def _observe_hil_dispatch_lag(record: HILApprovalRecord) -> None:
    """Record decision-to-resume lag at the dispatch, the only point it exists."""
    try:
        if record.decided_at is None:
            return
        lag_s = (datetime.now(UTC) - record.decided_at).total_seconds()
    except TypeError:  # naive/aware mix — not a measurement
        return
    if lag_s < 0.0:  # clock skew between the decider and this worker
        return
    observe_hil_dispatch_lag(lag_s)
    log.set(hil={"dispatch_lag_s": round(lag_s, 2)})


async def sweep_approvals() -> SweepCounts:
    """Resolve expired approvals and re-dispatch crashed resumes. Cron-driven.

    Two passes: pending past expires_at resolve as timeout (or close directly if
    the executor died before registering the pause); decided but never resumed
    (crash between the decided-transition and the run spawn) re-dispatch from
    the record's resume_item.
    """
    expired = 0
    for record in await list_expired_pending():
        try:
            await _resolve_or_close(record, user_id=record.user_id, kind="timeout", feedback=None)
            expired += 1
        except ApprovalRequestNotFoundError:
            continue
        except Exception as e:  # one bad record must not strand the rest of the pass
            log.error(
                f"{LogTag.HIL} Sweep could not expire",
                approval_id=record.approval_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    redispatched = 0
    for record in await list_decided_unresumed(HIL_DECIDED_UNRESUMED_GRACE_SECONDS):
        try:
            await _dispatch_decided(record)
            redispatched += 1
        except Exception as e:  # a failed redispatch is retried next sweep; don't abort
            log.error(
                f"{LogTag.HIL} Sweep could not redispatch",
                approval_id=record.approval_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if expired or redispatched:
        log.info(f"{LogTag.HIL} Approval sweep", expired=expired, redispatched=redispatched)
    return {"expired": expired, "redispatched": redispatched}
