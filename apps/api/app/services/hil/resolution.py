"""Apply a HIL decision and resume the executor run it paused.

The single entry point for every decision source — approval buttons, a bot's
interactive component, the conversational resolver, and the timeout sweep. Each
supplies a ``DecisionKind``; everything else is identical.

Two guarantees:

* **Exactly once.** The ``pending -> decided`` transition is a conditional Mongo
  update. A double click, a racing bot callback, and a sweep firing against an
  approval the user just answered all lose the race and resolve nothing.
* **The run always continues.** Whatever the decision, the paused thread is
  re-dispatched so it either performs the action or tells the model it was
  refused. A resolved approval that never resumed would strand the conversation's
  executor lock until its TTL.
"""

import asyncio
from http import HTTPStatus
from typing import Any, Literal, cast

from langgraph.types import Command

from app.agents.core.background.executor_queue import (
    ExecutorRunItem,
    is_executor_busy,
    prepare_run_from_item,
)
from app.agents.core.background.executor_runner import run_executor_background
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
from app.services.hil.resume_slot import claim_resume_dispatch, release_resume_dispatch
from app.utils.errors import AppError
from shared.py.wide_events import log

DecisionKind = Literal["approve", "deny", "timeout", "abandon"]

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

    The record stays ``pending`` — committing the decision without a resumable
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
    means only the first decision actually dispatches the executor, and the join
    round it wakes collects the rest. One failed item never blocks the others —
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

    ``cancel_executor`` stops the run and drops the conversation's busy lock, but the
    approval records are the *decision* state, and they outlive both: left pending, a
    later "Approve" — or the timeout sweep, with no user involved at all — re-dispatches
    the very run the user stopped, on a fresh stream the cancel flag does not cover.
    Deciding them here is what makes a cancel stick.

    Deliberately does NOT resume, which is the whole difference from
    ``abandon_conversation_approvals``: there the run must wake up to release the lock,
    here it is already gone. ``mark_decided`` runs first because it is the exactly-once
    mutex — only the caller that wins the transition owns the record and may clear its
    ``resume_item``, so a decision landing at the same instant can never lose its
    re-dispatch context.
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

    A record with no ``resume_item`` never had its pause registered — the executor died
    between publishing the card and recording how to restart it. There is nothing to
    resume, so resolving it would only raise. Closing it is what matters: a record left
    pending goes on hijacking every later message in the conversation via the
    conversational resolver.
    """
    if record.resume_item is None:
        log.warning(
            f"{LogTag.HIL} Closing approval with no resume context",
            approval_id=record.approval_id,
        )
        await mark_decided(
            record.approval_id,
            _TERMINAL_STATUS[kind],
            feedback=feedback,
            scope="once",
            decided_by=None,
        )
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
    # Checked BEFORE the decided-transition: a decision we cannot act on must
    # fail the request (record stays pending; the sweep expires it), never
    # report success for an action that will silently not run.
    #
    # Exception: a parked-subagent record (stamped ``subagent_thread_id``) decided
    # BEFORE the executor reaches its join has no resume context yet — and needs
    # none, PROVIDED a collector is actually alive. The busy lock is that proof:
    # held means an executor run (running or parked) will reach a join and read
    # this decision durably. A finished executor (fire-and-forget dispatch, or
    # one that never called wait_for_subagents) means nobody will ever collect —
    # accepting the decision then is a false "going ahead" for an action that
    # will never run, so it must fail loudly instead.
    if record.resume_item is None:
        collector_alive = record.subagent_thread_id is not None and await is_executor_busy(
            record.conversation_id
        )
        # An APPROVE with no run to carry it out is a false "going ahead" (nobody would
        # execute it), so fail loudly and let the sweep expire it. A deny/timeout/abandon
        # needs no run at all, since its whole point is that the action does NOT happen, so
        # it is safe to record even with no collector. Closing it here stops the pending
        # record hijacking the conversation, which is what a batch "Decline all" over such
        # a record used to do: it raised and orphaned the record pending.
        if not collector_alive and kind == "approve":
            log.error(f"{LogTag.HIL} No resume context on record", approval_id=record.approval_id)
            raise ApprovalNotResumableError()

    decided_by = None if kind == "timeout" else user_id
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

    log.set(hil={"approval_id": record.approval_id, "decision": kind, "tool": record.tool_name})
    resume_status = "denied" if kind == "abandon" else _TERMINAL_STATUS[kind]
    if record.resume_item is None:
        # No run to dispatch: either a live collector (a parked subagent whose executor
        # reads this decision at its join) or an un-resumable deny/timeout/abandon closed
        # in place. Nothing to resume here either way.
        log.info(
            f"{LogTag.HIL} Decision recorded without a resume dispatch",
            approval_id=record.approval_id,
        )
        return record
    await _dispatch_resume(record, resume_status=resume_status, feedback=feedback, scope=scope)
    return record


async def _dispatch_resume(
    record: HILApprovalRecord, *, resume_status: str, feedback: str | None, scope: str
) -> None:
    """Re-dispatch the executor thread this approval paused.

    ``prepare_run_from_item`` seizes the conversation's busy lock (the original
    owner's process is long gone) and gives the resumed run its own stream, so the
    frontend can watch it finish. ``mark_resumed`` stamps the record so the sweep
    knows this decision made it to a run; a crash before the stamp is re-dispatched
    by the sweep from ``resume_item``.

    At most one resume runs per conversation: a batch pause has several approvals
    sharing one executor thread, and two decisions landing close together must not
    start two concurrent LangGraph runs on it (checkpoint corruption). The loser
    of the claim skips dispatch — its decision is already durable on the record,
    and the in-flight join round or the sweep collects it.
    """
    if not await claim_resume_dispatch(record.conversation_id):
        log.info(
            f"{LogTag.HIL} Resume already in flight for conversation; decision will be "
            "collected by the running round or the sweep",
            approval_id=record.approval_id,
        )
        return

    # set_resume_item is the only writer of this field and now takes an
    # ExecutorRunItem, so the stored shape is correct by construction; Mongo just
    # hands it back as a plain dict. cast rather than isinstance (item 12) —
    # ExecutorRunItem is total=False, so {} is a valid empty item.
    prepared = await prepare_run_from_item(
        record.conversation_id, cast(ExecutorRunItem, record.resume_item or {})
    )
    if prepared is None:
        log.error(f"{LogTag.HIL} Could not prepare resume run", approval_id=record.approval_id)
        await release_resume_dispatch(record.conversation_id)
        return

    resume: Command[Any] = Command(
        resume={
            "status": resume_status,
            "feedback": feedback,
            "scope": scope,
            # Identifies which gate this decision is for. A synchronous spawn/handoff
            # that gated several calls in sequence replays the executor's resume list
            # positionally on recovery; the driver matches on this to hand each gate
            # its own decision instead of the first one (see subagent_runner.resume_for_gate).
            "approval_id": record.approval_id,
        }
    )
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
    await mark_resumed(record.approval_id)
    log.info(f"{LogTag.HIL} Resumed paused executor run", approval_id=record.approval_id)


async def sweep_approvals() -> dict[str, int]:
    """Resolve expired approvals and re-dispatch crashed resumes. Cron-driven.

    Two passes:
    - pending past ``expires_at`` → resolved as timeout (the run resumes and is
      told the request expired). Records that never got resume context — the
      executor died before registering the pause — are closed directly.
    - decided but never resumed (crash between the decided-transition and the
      run spawn) → re-dispatched from the record's ``resume_item``.
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
            resume_status = "denied" if record.status == "abandoned" else record.status
            await _dispatch_resume(
                record, resume_status=resume_status, feedback=record.feedback, scope=record.scope
            )
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
