"""Decide ledger approvals: CAS commit, ticket wake, agent redeem.

The single entry point for every ledger decision source (web/mobile decide
endpoints, later the bot classifier). Approval is permission, not execution:
the backend never runs an approved tool. Committing wakes the model with the
ticket (the approval id); the model redeems it with
execute(tool_name="approve", data={"id": ...}), which runs the stored
envelope and returns the result so dependent work can chain on it.
Guarantees (mirror resolution.py): the PENDING -> decided transition is a
conditional Mongo update, so double taps and stale clients lose the race and
refresh instead of overwriting; a mismatched row version v returns the current
row with committed=False; stale approvals carry their age for the model to
judge at redeem; redeem's APPROVED -> EXECUTING claim is single-use; and crash
recovery runs lazily via reconcile_conversation_ledger, with no daemon.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import (
    break_holder_lock,
    get_lock_holder,
    parse_lock_value,
)
from app.agents.core.background.session import get_session
from app.agents.tools.execute.dispatch import (
    DispatchErrorKind,
    dispatch_config_for,
    dispatch_tool,
)
from app.constants.agents import AgentTag
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.constants.general import EXECUTOR_THREAD_PREFIX
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversations import conversation_repository
from app.models.hil_models import (
    ApprovalLedgerDocument,
    HILApprovalStatus,
    LedgerState,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import BatchDecisionItem, BatchDecisionOutcome
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.hil.approvals_store import list_pending_for_conversation
from app.services.hil.bridge import (
    _approval_entry,
    _publish_entry,
    settle_session_approval_frame,
    sync_conversation_approval_flag,
)
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)
from app.services.hil.resume import record_owner_deny, resume_owner_after_approval
from app.services.hil.utils import GatedCall
from shared.py.wide_events import log

DecisionKind = Literal["approve", "deny"]

# A redeem that dies between claim and receipt leaves EXECUTING behind.
# Reconciled lazily to UNKNOWN on the decide path — there is no sweeper by
# design, so this cutoff is the only crash detector.
STALLED_EXECUTING_MINUTES = 10


@dataclass(frozen=True)
class LedgerDecision:
    """What one decide call did: committed or current-row refresh."""

    committed: bool
    approval_id: str
    prior_state: LedgerState
    state: LedgerState
    # Approved but blocked_by unresolved: sits in APPROVED as the queue, no
    # execution scheduled. Ordering chains (claim rule + dep_unmet reconciler)
    # arrive in Phase 3; this flag is their seam.
    queued: bool = False
    # The call lost on version, not on state: the row may still be PENDING.
    # Callers must report "stale/refresh", never "not found", or clients drop
    # live cards they should keep.
    stale: bool = False


@dataclass(frozen=True)
class RedeemResult:
    """What one ticket redeem did: ran the stored envelope, or refused."""

    ok: bool
    approval_id: str
    state: LedgerState
    # The tool's output on success, the error detail on failure, the refusal
    # reason when the ticket could not be honored (already redeemed, wrong
    # owner, stale row). Never None — the caller always has words.
    detail: str


async def decide_ledger(
    approval_id: str,
    *,
    user_id: str,
    kind: DecisionKind,
    feedback: str | None = None,
    v: int | None = None,
) -> LedgerDecision:
    """Commit one decision and wake the model with the ticket. Never blocks."""
    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is None:
        raise ApprovalRequestNotFoundError()
    # Strict match, no empty bypass: a row without an owner must never be
    # decidable by whoever asks first. The gate always stamps a real id.
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()

    if v is not None and v != row.v:
        return LedgerDecision(
            committed=False,
            approval_id=approval_id,
            prior_state=row.state,
            state=row.state,
            stale=True,
        )

    # Approve+feedback is a conditional approval, but envelopes carry no
    # conditions: route it to deny (as the chat classifier does) so nothing
    # runs beyond the granted permission; the note is attached to the denial.
    if kind == "approve" and feedback is not None and feedback.strip() != "":
        kind = "deny"

    target = LedgerState.APPROVED if kind == "approve" else LedgerState.DENIED
    transitioned = await approval_ledger_repository.transition(
        approval_id, LedgerState.PENDING, target, decided_by=user_id, feedback=feedback
    )
    if not transitioned:
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        state = current.state if current is not None else row.state
        return LedgerDecision(
            committed=False,
            approval_id=approval_id,
            prior_state=row.state,
            state=state,
        )

    log.set(hil={"approval_id": approval_id, "decision": kind, "tool": row.tool_name})
    # Server-owned funnel event: exactly once per committed decision (stale-v
    # and lost-CAS returns above emit nothing). Explicit user_id: the decide
    # path resolves its user from the row, not a session.
    card_age_seconds: float | None = None
    if row.created_at is not None:
        card_age_seconds = (datetime.now(UTC) - row.created_at).total_seconds()
    capture_event(
        user_id,
        AnalyticsEvents.HIL_DECISION_SUBMITTED,
        {
            "approval_id": approval_id,
            "decision": target.value,
            "card_age_seconds": card_age_seconds,
            # The transition $incs v: the committed version is row.v + 1.
            "ledger_version": row.v + 1,
        },
    )
    queued = bool(target is LedgerState.APPROVED and row.blocked_by)
    if target is LedgerState.APPROVED and not queued:
        # Permission granted: hand the ticket to the model. deliver_to_executor
        # steers a live run or starts an idle one; on failure fall back to the
        # inbox wake, since the decision already committed and must not fail the tap.
        try:
            await _deliver_ticket(row)
        except Exception as e:
            log.error(
                f"{LogTag.HIL} Ledger ticket delivery failed; falling back to inbox wake",
                approval_id=approval_id,
                error_type=type(e).__name__,
            )
            await _wake_agent(row, "APPROVED", None)
        # A background owner parked on this approval has no live run to wake:
        # re-enqueue its unit of work (todo re-execution, workflow continuation).
        # Best-effort and claim-guarded — never fails the tap.
        await resume_owner_after_approval(row)
    await publish_ledger_decision(row, target, feedback=feedback)
    await sync_conversation_approval_flag(row.conversation_id, row.user_id)
    if target is LedgerState.DENIED:
        # Denials schedule nothing, but the agent still needs the verdict and a
        # wake alone only reaches a running run — deliver, so an idle
        # conversation starts one that reports what was skipped.
        await _deliver_verdict(row, "DENIED", feedback)
        # A background todo has no other surface: leave the skip in its log.
        await record_owner_deny(row, feedback)
    elif queued:
        await _wake_agent(row, "QUEUED", f"waiting on {','.join(row.blocked_by)}")
    await reconcile_conversation_ledger(row.conversation_id)
    return LedgerDecision(
        committed=True,
        approval_id=approval_id,
        prior_state=LedgerState.PENDING,
        state=target,
        queued=queued,
    )


async def decide_ledger_batch(
    user_id: str, decisions: list[BatchDecisionItem]
) -> list[BatchDecisionOutcome]:
    """Apply several ledger decisions in one submission — the batch review's ledger path.

    Mirrors resolve_approvals_batch: each item commits exactly once and one
    already-decided, forbidden or failing item never blocks the rest. No resume
    dispatch exists here — execution and wake already happened in decide_ledger.
    """
    outcomes: list[BatchDecisionOutcome] = []
    for item in decisions:
        try:
            outcome = await decide_ledger(
                item.approval_id,
                user_id=user_id,
                kind=item.decision,
                feedback=item.feedback,
                v=item.v,
            )
        except ApprovalRequestNotFoundError:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id, resolved=False, reason="not_found"
                )
            )
            continue
        except ApprovalRequestForbiddenError:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id, resolved=False, reason="forbidden"
                )
            )
            continue
        except Exception as e:  # one item's infra failure must not strand the rest
            log.error(
                f"{LogTag.HIL} Ledger batch decision failed for",
                approval_id=item.approval_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            outcomes.append(
                BatchDecisionOutcome(approval_id=item.approval_id, resolved=False, reason="error")
            )
            continue
        if outcome.committed:
            outcomes.append(BatchDecisionOutcome(approval_id=item.approval_id, resolved=True))
        else:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id,
                    resolved=False,
                    reason="stale" if outcome.stale else "not_found",
                    status=outcome.state.value,
                )
            )
    return outcomes


# A busy-lock holder older than this with no live session is provably dead,
# not parked (parked/live runs keep a session). A mistaken break only costs a
# redundant run, never a duplicate: the ticket-claim CAS still bounds execution.
STALE_HOLDER_MIN_AGE_SECONDS = 300


def _ticket_task(row: ApprovalLedgerDocument) -> str:
    """Build the wake that turns an approval into a redeem: id, age, and the execute call that honors it."""
    age = "unknown age"
    if row.created_at is not None:
        elapsed_minutes = int((datetime.now(UTC) - row.created_at).total_seconds()) // 60
        hours, minutes = divmod(elapsed_minutes, 60)
        age = f"{hours}h{minutes}m old"
    return (
        f"APPROVAL_READY {row.approval_id}: the user approved {row.summary} "
        f'({age}). Run it now with execute(tool_name="approve", '
        f'data={{"id": "{row.approval_id}"}}) and continue with its result. '
        "If it is no longer needed, say so instead of running it."
    )


async def _reclaim_dead_holder(conversation_id: str) -> bool:
    """Release a busy lock whose holder is provably gone; True when free.

    A dead holder bricks delivery (deliver_to_executor appends to an inbox no
    live run drains). Reclaim only when all hold: lock present, stream has no
    live session, older than STALE_HOLDER_MIN_AGE, no paused executor approval.
    Compare-and-delete; never raises — on any doubt the lock stands.
    """
    try:
        holder = await get_lock_holder(conversation_id)
        if holder is None:
            return True
        stream_id, _ = parse_lock_value(holder)
        if stream_id and get_session(stream_id) is not None:
            return False
        if redis_cache.client is None:
            return True
        ttl = await redis_cache.client.ttl(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
        if ttl is None or ttl < 0:
            return True
        if EXECUTOR_BUSY_TTL - ttl < STALE_HOLDER_MIN_AGE_SECONDS:
            return False
        for record in await list_pending_for_conversation(conversation_id):
            if record.resume_item is not None:
                return False
        return await break_holder_lock(conversation_id, holder)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Holder reclaim check failed; keeping the lock",
            conversation_id=conversation_id,
            error_type=type(e).__name__,
        )
        return False


async def _deliver_ticket(row: ApprovalLedgerDocument) -> None:
    """Hand an approved ticket to the model — steer or start, never execute.

    Reclaims a provably-dead lock holder first, else a crashed run's lock
    bricks delivery into an inbox no live run drains. Deferred import:
    executor_runner reaches services.hil, so a top-level import risks closing
    a cycle (same guard as revoke_tool).
    """
    from app.agents.core.background.executor_runner import (  # noqa: PLC0415 -- same cycle guard as revoke_tool
        deliver_to_executor,
    )

    await _reclaim_dead_holder(row.conversation_id)
    await deliver_to_executor(
        row.conversation_id,
        AuthenticatedUser(user_id=row.user_id),
        _ticket_task(row),
    )


async def _deliver_verdict(row: ApprovalLedgerDocument, outcome: str, result: object) -> None:
    """Steer or start a run with a non-approve verdict (deny today).

    The inbox wake alone only reaches a running run; an idle conversation
    would never wrap up ("user said no" arrives nowhere). Delivery starts one
    when needed and degrades to the wake when delivery itself fails — the
    decision already committed, so this path never raises.
    """
    from app.agents.core.background.executor_runner import (  # noqa: PLC0415 -- same cycle guard as _deliver_ticket
        deliver_to_executor,
    )

    preview = "" if result is None else str(result)[:500]
    task = (
        f"DECISION {row.approval_id}={outcome} {row.summary}"
        + (f" :: {preview}" if preview else "")
        + " The user said no — report what you skipped and continue without it. "
        "Do not re-request it."
    )
    try:
        await _reclaim_dead_holder(row.conversation_id)
        await deliver_to_executor(
            row.conversation_id,
            AuthenticatedUser(user_id=row.user_id),
            task,
        )
    except Exception as e:
        log.error(
            f"{LogTag.HIL} Ledger verdict delivery failed; falling back to inbox wake",
            approval_id=row.approval_id,
            outcome=outcome,
            error_type=type(e).__name__,
        )
        await _wake_agent(row, outcome, result)


async def redeem_approved(
    approval_id: str,
    *,
    user_id: str,
    conversation_id: str,
    caller: str,
) -> RedeemResult:
    """Honor one ticket: run the stored envelope, return its outcome.

    The model supplies no args — the ticket IS the approval id and the row
    holds the envelope, so nothing the model says can drift the call. The
    APPROVED -> EXECUTING claim is the single-use CAS: exactly one redeemer
    wins, every loser is refused with the row's actual state.
    """

    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    # Unknown id and foreign conversation read identically: existence must
    # not leak across conversations (same contract as revoke_tool).
    if row is None or row.conversation_id != conversation_id:
        raise ApprovalRequestNotFoundError()
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    if row.state is not LedgerState.APPROVED:
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            state=row.state,
            detail=f"Already {row.state.value}; report that instead of retrying.",
        )
    if caller != row.owner_agent and not caller.startswith(EXECUTOR_THREAD_PREFIX):
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            state=row.state,
            detail="This ticket belongs to another worker; only its proposer or the executor may redeem it.",
        )
    claimed = await approval_ledger_repository.claim_executing(approval_id)
    if not claimed:
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        state = current.state if current is not None else row.state
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            state=state,
            detail=f"Already {state.value}; report that instead of retrying.",
        )
    try:
        result = await dispatch_tool(
            user_id=row.user_id or None,
            tool_name=row.tool_name,
            data=dict(row.args),
            # Identity-bearing config, not a bare configurable: the wrappers
            # resolve per-user auth from this (see dispatch_config_for).
            config=dispatch_config_for(row.user_id),
        )
    except Exception as e:
        await approval_ledger_repository.transition(
            approval_id, LedgerState.EXECUTING, LedgerState.UNKNOWN
        )
        cause = f"{type(e).__name__}: {e}"
        log.error(
            f"{LogTag.HIL} Ticket redeem raised; reconciled as UNKNOWN, never retried",
            approval_id=approval_id,
            error_type=type(e).__name__,
        )
        await _settle_terminal(row, LedgerState.UNKNOWN)
        await sync_conversation_approval_flag(row.conversation_id, row.user_id)
        return RedeemResult(
            ok=False, approval_id=approval_id, state=LedgerState.UNKNOWN, detail=cause
        )
    if (
        not result.ok
        and result.error is not None
        and result.error.kind == DispatchErrorKind.TIMEOUT
    ):
        state, detail = (
            LedgerState.UNKNOWN,
            "provider timed out; may or may not have run — never auto-retried",
        )
    elif result.ok:
        state, detail = LedgerState.EXECUTED, str(result.output)
    else:
        state, detail = (
            LedgerState.FAILED,
            result.error.detail if result.error is not None else "unknown error",
        )
    committed = await approval_ledger_repository.transition(
        approval_id, LedgerState.EXECUTING, state
    )
    if not committed:
        # A reconciler moved the row under us (stalled cutoff fired
        # mid-redeem): report what the ledger actually says, not what we
        # attempted. Never a silent overwrite of its verdict.
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        live = current if current is not None else row
        actual = live.state.value
        log.error(
            f"{LogTag.HIL} Ticket receipt lost its CAS; reporting actual state",
            approval_id=approval_id,
            attempted=state.value,
            actual=actual,
        )
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            state=live.state,
            detail=f"Already {actual}; report that instead of retrying.",
        )
    await _settle_terminal(row, state)
    await sync_conversation_approval_flag(row.conversation_id, row.user_id)
    return RedeemResult(ok=result.ok, approval_id=approval_id, state=state, detail=detail)


async def _settle_terminal(row: ApprovalLedgerDocument, state: LedgerState) -> None:
    """Settle the card to the redeem outcome (executed/failed/unknown).

    Without this the card lingers as approved while the ledger moved on. Same
    triple as every other settle here (persisted frame, broadcast, session
    flip); feedback stays None so the card collapses to the outcome chip.
    """
    if row.proposing_run_id:
        settle_session_approval_frame(row.proposing_run_id, row.approval_id, state.value)
    await _persist_decision_status(row, state.value)
    await _broadcast_decision(row, state.value, None)


async def revoke_ticket(
    approval_id: str, *, user_id: str, conversation_id: str, caller: str
) -> str:
    """Withdraw your own pending approval.

    The revoke half of the ticket convention (mirrors redeem_approved): the
    row tombstones as REVOKED; decided rows are untouchable, so report those
    instead. Unknown ids and foreign conversations read identically —
    existence must not leak across conversations.
    """

    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is None or row.conversation_id != conversation_id:
        return f"No pending approval with id '{approval_id}'."
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    if row.state is not LedgerState.PENDING:
        return (
            f"Cannot revoke '{approval_id}': already {row.state.value}. "
            "Report that to the user instead of retrying."
        )
    if caller != row.owner_agent and not caller.startswith(EXECUTOR_THREAD_PREFIX):
        return (
            f"Cannot revoke '{approval_id}': it belongs to another worker. "
            "Only its proposer or the executor can withdraw it."
        )
    revoked = await approval_ledger_repository.transition(
        approval_id, LedgerState.PENDING, LedgerState.REVOKED
    )
    if not revoked:
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        state = current.state.value if current else "gone"
        return f"Cannot revoke '{approval_id}': already {state}."
    revoked_row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if revoked_row is not None:
        await publish_ledger_revocation(revoked_row)
    await sync_conversation_approval_flag(row.conversation_id, row.user_id)
    capture_event(
        user_id,
        AnalyticsEvents.HIL_REVOKED,
        {
            "approval_id": approval_id,
            "ledger_version": row.v + 1,
            "revoker": caller,
        },
    )
    return f"Revoked '{approval_id}' ({row.summary}). It will never be asked."


async def cancel_ledger_approvals(conversation_id: str, user_id: str) -> list[str]:
    """Withdraw a cancelled run's pending ledger approvals so nothing revives them.

    Ledger twin of resolution.cancel_conversation_approvals: without it a later
    Approve (stale card, another tab, a bot "yes") redeems a ticket for stopped
    work. Only user-owned PENDING rows; APPROVED tickets stay. Each revocation
    tombstones through the full triple.
    """
    cancelled: list[str] = []
    for row in await approval_ledger_repository.list_open(conversation_id):
        if row.state is not LedgerState.PENDING or row.user_id != user_id:
            continue
        if not await approval_ledger_repository.transition(
            row.approval_id, LedgerState.PENDING, LedgerState.REVOKED
        ):
            continue
        current = await approval_ledger_repository.get_by_approval_id(row.approval_id)
        if current is not None:
            await publish_ledger_revocation(current)
        capture_event(
            user_id,
            AnalyticsEvents.HIL_REVOKED,
            {
                "approval_id": row.approval_id,
                "ledger_version": row.v + 1,
                "revoker": "cancelled-run",
            },
        )
        cancelled.append(row.approval_id)
    await sync_conversation_approval_flag(conversation_id, user_id)
    if cancelled:
        log.info(
            f"{LogTag.HIL} Withdrew pending ledger approvals for a cancelled run",
            conversation_id=conversation_id,
            approval_ids=cancelled,
        )
    return cancelled


async def reconcile_conversation_ledger(conversation_id: str) -> None:
    """Heal one conversation's ledger as a decide-path side effect.

    No daemon exists by design, so every decide repairs: stalled EXECUTING
    rows go UNKNOWN (with a wake). Orphaned APPROVED rows need nothing — the
    ticket lives in model context and only a redeem runs the envelope. Every
    step is CAS-guarded, so concurrent deciders converge instead of duplicating.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=STALLED_EXECUTING_MINUTES)
    for stalled in await approval_ledger_repository.list_stalled_executing(cutoff, conversation_id):
        if await approval_ledger_repository.transition(
            stalled.approval_id, LedgerState.EXECUTING, LedgerState.UNKNOWN
        ):
            log.error(
                f"{LogTag.HIL} Ledger execution stalled; reconciled as UNKNOWN, never retried",
                approval_id=stalled.approval_id,
            )
            await _settle_terminal(stalled, LedgerState.UNKNOWN)
            await _wake_agent(
                stalled,
                "UNKNOWN",
                "stalled execution reconciled; never retried. The action may or may not "
                "have run — verify before re-proposing, never blind-retry.",
            )
            await sync_conversation_approval_flag(conversation_id, stalled.user_id)


async def publish_ledger_decision(
    row: ApprovalLedgerDocument,
    status: LedgerState,
    *,
    feedback: str | None = None,
) -> None:
    """Settle the card where the user watches + persist the settled frame.

    Best-effort delivery, never fails the decision: the ledger row is the
    truth and every render re-reads it. Publishes the settled frame to the
    proposing stream when it is still live, persists the settled status for
    reload, and broadcasts so listening clients refresh.
    """
    mapped = (
        HILApprovalStatus.APPROVED if status is LedgerState.APPROVED else HILApprovalStatus.DENIED
    )
    entry = _approval_entry(
        row.approval_id,
        GatedCall(name=row.tool_name, id="", args=row.args),
        mapped,
        row.summary,
        None,
        feedback if feedback is not None else row.feedback,
    )
    if row.proposing_run_id:
        try:
            await _publish_entry(row.proposing_run_id, entry)
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} Ledger decision frame missed its stream",
                approval_id=row.approval_id,
                error_type=type(e).__name__,
            )
        # Flip the in-memory PENDING frame too: the drain persists whatever
        # the session holds, and without this a later drain resurrects the
        # unsettled card over the persisted decision.
        settle_session_approval_frame(
            row.proposing_run_id,
            row.approval_id,
            mapped.value,
            feedback if feedback is not None else row.feedback,
        )
    await _persist_decision_status(row, mapped.value)
    await _broadcast_decision(row, mapped.value, feedback if feedback is not None else row.feedback)


async def publish_ledger_revocation(row: ApprovalLedgerDocument) -> None:
    """Surface an agent-side revoke: tombstone, not a silent row change.

    Without this, a revoked card stays actionable in every open client
    forever — the tombstone UI would be unreachable. Best-effort like every
    other delivery here: the row is the truth, frames are hints.
    """
    if row.proposing_run_id:
        # A revoke before the run ends drops the unshown frame (a held card
        # never went live, so there is nothing to explain); a frame already
        # live still flips to the tombstone.
        settle_session_approval_frame(
            row.proposing_run_id, row.approval_id, "revoked", drop_if_unpublished=True
        )
    await _persist_decision_status(row, "revoked")
    await _broadcast_decision(row, "revoked", None)


async def _persist_decision_status(row: ApprovalLedgerDocument, status: str) -> None:
    """Settle the persisted card frame so reload renders the terminal state.

    Isolated on purpose (mirrors bridge.publish_decision): a write error here
    must never fail the decision or revocation it reports on.
    """
    try:
        await conversation_repository.set_message_approval_status(
            row.conversation_id,
            user_id=row.user_id,
            approval_id=row.approval_id,
            status=status,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Ledger decision persist missed; live delivery already attempted",
            approval_id=row.approval_id,
            error_type=type(e).__name__,
        )


async def _broadcast_decision(
    row: ApprovalLedgerDocument, status: str, feedback: str | None
) -> None:
    """Tell listening clients a card settled — same shape for decide + revoke."""
    try:
        await websocket_manager.broadcast_to_user(
            user_id=row.user_id,
            message={
                "type": "hil_approval_decided",
                "data": {
                    "conversation_id": row.conversation_id,
                    "approval_id": row.approval_id,
                    "status": status,
                    "feedback": feedback,
                    "version": row.v + 1,
                },
            },
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Ledger decision broadcast missed",
            approval_id=row.approval_id,
            error_type=type(e).__name__,
        )


async def _wake_agent(row: ApprovalLedgerDocument, outcome: str, result: object) -> None:
    """One DECISIONS line into the executor inbox — the agent's only signal.

    Inbox is transport, ledger is truth: a lost wake re-surfaces via the next
    OPEN PENDINGS injection, never via re-execution. A missing Redis client is
    a loud error, never a silent drop — append no-ops without one, so this
    checks first instead of reporting a delivery that never happened.
    """
    if redis_cache.client is None:
        log.error(
            f"{LogTag.HIL} Ledger wake dropped: no Redis client; agent will not learn this outcome",
            approval_id=row.approval_id,
            outcome=outcome,
        )
        return
    preview = "" if result is None else str(result)[:500]
    try:
        await ExecutorInbox(row.conversation_id).append(
            str(uuid4()),
            f"DECISIONS: {row.approval_id}={outcome} {row.summary}"
            + (f" :: {preview}" if preview else ""),
            AgentTag.HIL_DECISION,
        )
    except Exception as e:
        log.error(
            f"{LogTag.HIL} Ledger wake failed; outcome lives on the row only",
            approval_id=row.approval_id,
            outcome=outcome,
            error_type=type(e).__name__,
        )
