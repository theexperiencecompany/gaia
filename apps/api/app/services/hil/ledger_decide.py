"""Decide approvals in the conversation log, wake the agent with the ticket, and redeem it.

The single entry point for every decision source (card, batch review, a chat reply).
Approval is permission, not execution: committing wakes the model with the ticket
(the approval id), and the model redeems it with execute(tool_name="approve",
data={"id": ...}), which runs the envelope the ledger stored for it.

The log is the approval's only truth: a decision is an ApprovalDecided append, and
the first one wins, so a double tap or a tap on an expired or stopped approval reads
back the decision already logged. The ledger follows the log, as the fingerprint
index and the envelope; its action claim keeps a redeem single-use. Every decision's
hand-off to the waiting work is leased on the row, so the conversation sweeper carries
out one that failed, and expires approvals nobody decided.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.tools.execute.dispatch import (
    dispatch_config_for,
    dispatch_tool,
)
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.general import EXECUTOR_THREAD_PREFIX
from app.constants.hil import DECISION_HANDOFF_LEASE, DECISION_OUTCOME, ApprovalDecision
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.conversation_log_models import ApprovalDecided, ApprovalRequested
from app.models.execute_models import DispatchErrorKind
from app.models.hil_models import ApprovalLedgerDocument
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import (
    ApprovalDecisionRequest,
    BatchDecisionItem,
    BatchDecisionOutcome,
    DecisionRefusal,
)
from app.services.analytics_service import capture
from app.services.conversation.screen import decided_status
from app.services.conversation.work_log import (
    DecisionTaken,
    logged_decision,
    logged_status,
    record_approval_decided,
    record_approved_action_ended,
)
from app.services.hil.errors import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
    LedgerDriftError,
    LedgerWakeUndeliveredError,
    ToolAlwaysAsksError,
)
from app.services.hil.policy import asks_every_time, resolved_tool_key
from app.services.hil.preferences import set_tool_override
from app.services.hil.resume import record_owner_deny, resume_owner_after_approval
from app.services.hil.ticket import amend_instruction, approval_ticket
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import (
    ApprovalDecided as ApprovalDecidedEvent,
    HilDecisionSubmitted,
    HilDecisionVia,
    HilRevoked,
)
from shared.py.approvals import (
    DECIDED_OUTCOMES,
    ActionResult,
    ApprovalDecider,
    ApprovalOutcome,
    ApprovalStatus,
    UndecidedOutcome,
)
from shared.py.wide_events import log

# A redeem that dies between claim and receipt leaves its action executing.
# Reconciled lazily to unknown on the decide path — the conversation sweeper expires
# undecided approvals, not running actions, so this cutoff is the only crash detector.
STALLED_EXECUTING_MINUTES = 10


@dataclass(frozen=True)
class LedgerDecision:
    """What one decide call did: committed or current-row refresh."""

    committed: bool
    approval_id: str
    # The row's two facts after the call: what was committed, or what a refresh read.
    outcome: ApprovalOutcome | None
    action: ActionResult | None


@dataclass(frozen=True)
class RedeemResult:
    """What one ticket redeem did: ran the stored envelope, or refused."""

    ok: bool
    approval_id: str
    # The action's result; None when the ticket was refused before anything ran.
    action: ActionResult | None
    # The tool's output on success, the error detail on failure, the refusal
    # reason when the ticket could not be honored (already redeemed, wrong
    # owner, stale row). Never None — the caller always has words.
    detail: str


async def decide_ledger(
    approval_id: str,
    *,
    user_id: str,
    kind: ApprovalDecision,
    feedback: str | None = None,
    via: HilDecisionVia,
) -> LedgerDecision:
    """Commit one decision and wake the model with the ticket. Never blocks."""
    row = await _owned_row(approval_id, user_id)
    return await _commit_decision(row, user_id=user_id, kind=kind, feedback=feedback, via=via)


async def decide_ledger_card(
    approval_id: str, *, user_id: str, tap: ApprovalDecisionRequest
) -> LedgerDecision:
    """Commit a card tap; an approved "always" tap also stops asking for the tool."""
    row = await _owned_row(approval_id, user_id)
    if tap.scope == "always_tool" and await asks_every_time(user_id, row.tool_name, row.args):
        raise ToolAlwaysAsksError()
    decision = await _commit_decision(
        row, user_id=user_id, kind=tap.decision, feedback=tap.feedback, via="card"
    )
    if (
        tap.scope == "always_tool"
        and decision.committed
        and decision.outcome is ApprovalOutcome.APPROVED
        and _change(tap.feedback) is None
    ):
        tool_key = row.tool_key or await resolved_tool_key(user_id, row.tool_name)
        await set_tool_override(user_id, tool_key, False)
    return decision


def _change(feedback: str | None) -> str | None:
    """Return what the user asked to change, None for a decision with nothing to say."""
    return feedback if feedback and feedback.strip() else None


async def _owned_row(approval_id: str, user_id: str) -> ApprovalLedgerDocument:
    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is None:
        raise ApprovalRequestNotFoundError()
    # Strict match, no empty bypass: a row without an owner must never be
    # decidable by whoever asks first. The gate always stamps a real id.
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    return row


async def _commit_decision(
    row: ApprovalLedgerDocument,
    *,
    user_id: str,
    kind: ApprovalDecision,
    feedback: str | None,
    via: HilDecisionVia,
) -> LedgerDecision:
    approval_id = row.approval_id
    feedback = _change(feedback)
    target = DECISION_OUTCOME[kind]
    taken = await _decide(row, target, ApprovalDecider.USER, feedback=feedback)
    if not taken.taken:
        return LedgerDecision(
            committed=False,
            approval_id=approval_id,
            outcome=taken.stands.outcome,
            action=taken.stands.action,
        )
    log.set(hil={"approval_id": approval_id, "decision": kind, "tool": row.tool_name})
    # Server-owned funnel event: exactly once per committed decision (stale-v
    # and lost-CAS returns above emit nothing). Explicit user_id: the decide
    # path resolves its user from the row, not a session.
    card_age_seconds: float | None = None
    if row.created_at is not None:
        card_age_seconds = (datetime.now(UTC) - row.created_at).total_seconds()
    capture(
        UserId(user_id),
        HilDecisionSubmitted(
            approval_id=approval_id,
            decision=target,
            tool_name=row.tool_name,
            via=via,
            card_age_seconds=card_age_seconds,
            ledger_version=row.v + 1,
        ),
    )
    capture(UserId(user_id), ApprovalDecidedEvent(outcome=target))
    await reconcile_conversation_ledger(row.conversation_id)
    return LedgerDecision(
        committed=True,
        approval_id=approval_id,
        outcome=target,
        action=None,
    )


async def decide_ledger_batch(
    user_id: str, decisions: list[BatchDecisionItem]
) -> list[BatchDecisionOutcome]:
    """Apply several decisions in one submission, the batch review.

    Each item commits exactly once, and one already-decided, forbidden or failing
    item never blocks the rest.
    """
    outcomes: list[BatchDecisionOutcome] = []
    for item in decisions:
        try:
            outcome = await decide_ledger(
                item.approval_id,
                user_id=user_id,
                kind=item.decision,
                feedback=item.feedback,
                via="batch",
            )
        except ApprovalRequestNotFoundError:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id, resolved=False, reason=DecisionRefusal.NOT_FOUND
                )
            )
            continue
        except ApprovalRequestForbiddenError:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id, resolved=False, reason=DecisionRefusal.FORBIDDEN
                )
            )
            continue
        except Exception as e:  # one item's infra failure must not strand the rest
            log.error(
                f"{LogTag.HIL} Ledger batch decision failed; that item stays pending",
                approval_id=item.approval_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id, resolved=False, reason=DecisionRefusal.ERROR
                )
            )
            continue
        if outcome.committed:
            outcomes.append(BatchDecisionOutcome(approval_id=item.approval_id, resolved=True))
        else:
            outcomes.append(
                BatchDecisionOutcome(
                    approval_id=item.approval_id,
                    resolved=False,
                    reason=DecisionRefusal.ALREADY_DECIDED,
                    outcome=outcome.outcome,
                    action=outcome.action,
                )
            )
    resolved = sum(1 for outcome in outcomes if outcome.resolved)
    if resolved:
        capture(
            UserId(user_id),
            ApprovalDecidedEvent(batch=True, decisions=len(decisions), resolved=resolved),
        )
    return outcomes


async def _deliver_ticket(row: ApprovalLedgerDocument, decision: ApprovalDecided) -> None:
    """Hand an approved ticket to the model — steer or start, never execute.

    Delivery reclaims a dead holder's lock, so a crashed run never bricks it.
    Deferred import: executor_runner reaches services.hil, so a top-level
    import risks closing a cycle (same guard as revoke_tool).
    """
    from app.agents.core.background.executor_runner import (  # noqa: PLC0415 -- same cycle guard as revoke_tool
        deliver_to_executor,
    )

    await deliver_to_executor(
        row.conversation_id,
        AuthenticatedUser(user_id=row.user_id),
        approval_ticket(row, decision),
        continues=row.task_id,
    )


#: The statuses of an approval nobody can decide any more, as the outcome a decision on it ends it with.
_LET_GO: dict[ApprovalStatus, ApprovalOutcome] = {
    ApprovalStatus.EXPIRED: ApprovalOutcome.EXPIRED,
    ApprovalStatus.CANCELLED: ApprovalOutcome.CANCELLED,
    ApprovalStatus.WITHDRAWN: ApprovalOutcome.WITHDRAWN,
}

_VERDICT_INSTRUCTIONS: dict[ApprovalOutcome, str] = {
    ApprovalOutcome.DENIED: "The user said no",
    ApprovalOutcome.EXPIRED: "Nobody answered before it expired",
    ApprovalOutcome.WITHDRAWN: "Its request was lost before anyone could answer it",
}


async def _deliver_verdict(
    row: ApprovalLedgerDocument, outcome: ApprovalOutcome, result: object
) -> None:
    """Steer or start a run with a verdict that did not approve; a failed delivery raises to its decider."""
    await _deliver_verdict_task(
        row.conversation_id,
        row.user_id,
        _verdict_task(row.approval_id, row.summary, outcome, result),
        row.task_id,
    )


def _verdict_task(approval_id: str, summary: str, outcome: ApprovalOutcome, result: object) -> str:
    """Word a verdict that did not approve as the task the waiting work resumes with.

    Framed as a decision, not a request: it continues the delegation that asked, so the
    completion guard counts that work instead of sending a report-only resume back to it.
    """
    preview = "" if result is None else str(result)[:500]
    return wrap_agent_payload(
        AgentTag.HIL_DECISION,
        f"DECISION {approval_id}={outcome.upper()} {summary}"
        + (f" :: {preview}" if preview else "")
        + f" {_VERDICT_INSTRUCTIONS[outcome]} — report what you skipped and continue without it. "
        "Do not re-request it.",
    )


async def _deliver_verdict_task(
    conversation_id: str, user_id: str, task: str, asked_by: str | None
) -> None:
    from app.agents.core.background.executor_runner import (  # noqa: PLC0415 -- same cycle guard as _deliver_ticket
        deliver_to_executor,
    )

    await deliver_to_executor(
        conversation_id, AuthenticatedUser(user_id=user_id), task, continues=asked_by
    )


def _redeem_refusal(
    row: ApprovalLedgerDocument, decided: ApprovalDecided | None, caller: str
) -> RedeemResult | None:
    """Return why this ticket cannot run its stored call now, None when it may."""
    if decided is None or decided.outcome is not ApprovalOutcome.APPROVED or decided.action:
        return RedeemResult(
            ok=False,
            approval_id=row.approval_id,
            action=None if decided is None else decided.action,
            detail=f"Already {_standing(decided)}; report that instead of retrying.",
        )
    if decided_status(decided) is ApprovalStatus.APPROVED_WITH_CHANGE:
        return RedeemResult(
            ok=False,
            approval_id=row.approval_id,
            action=None,
            detail=(
                f"Approved with a change ({decided.feedback!r}); this stored call lacks it: "
                f"{amend_instruction(row)}."
            ),
        )
    if caller != row.owner_agent and not caller.startswith(EXECUTOR_THREAD_PREFIX):
        return RedeemResult(
            ok=False,
            approval_id=row.approval_id,
            action=row.action,
            detail="This ticket belongs to another worker; only its proposer or the executor may redeem it.",
        )
    return None


async def redeem_approved(
    approval_id: str,
    *,
    user_id: str,
    conversation_id: str,
    caller: str,
    run_config: RunnableConfig,
) -> RedeemResult:
    """Honor one ticket: run the stored envelope inside run_config's run, return its outcome.

    The model supplies no args — the ticket IS the approval id and the row
    holds the envelope, so nothing the model says can drift the call. The
    claim that starts the action is the single-use CAS: exactly one redeemer
    wins, every loser is refused with the row's actual state.
    """

    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    # Unknown id and foreign conversation read identically: existence must
    # not leak across conversations (same contract as revoke_tool).
    if row is None or row.conversation_id != conversation_id:
        raise ApprovalRequestNotFoundError()
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    decided = await logged_decision(row.conversation_id, row.user_id, approval_id)
    refused = _redeem_refusal(row, decided, caller)
    if refused is not None:
        return refused
    claimed = await approval_ledger_repository.claim_executing(approval_id)
    if not claimed:
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        now = current if current is not None else row
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            action=now.action,
            detail=f"Already {now.standing}; report that instead of retrying.",
        )
    try:
        result = await dispatch_tool(
            user_id=row.user_id or None,
            tool_name=row.tool_name,
            data=dict(row.args),
            account=row.account,
            # The row's identity on the redeeming run: wrappers resolve per-user
            # auth from it, and the tool's cards stream on that run.
            config=dispatch_config_for(row.user_id, run_config),
        )
    except Exception as e:
        await approval_ledger_repository.finish_action(approval_id, ActionResult.UNKNOWN)
        cause = f"{type(e).__name__}: {e}"
        log.error(
            f"{LogTag.HIL} Ticket redeem raised; reconciled as UNKNOWN, never retried",
            approval_id=approval_id,
            error_type=type(e).__name__,
        )
        await _settle_terminal(row, ActionResult.UNKNOWN)
        return RedeemResult(
            ok=False, approval_id=approval_id, action=ActionResult.UNKNOWN, detail=cause
        )
    if (
        not result.ok
        and result.error is not None
        and result.error.kind == DispatchErrorKind.TIMEOUT
    ):
        action, detail = (
            ActionResult.UNKNOWN,
            "provider timed out; may or may not have run — never auto-retried",
        )
    elif result.ok:
        action, detail = ActionResult.EXECUTED, str(result.output)
    else:
        action, detail = (
            ActionResult.FAILED,
            result.error.detail if result.error is not None else "unknown error",
        )
    committed = await approval_ledger_repository.finish_action(approval_id, action)
    if not committed:
        # A reconciler moved the row under us (stalled cutoff fired
        # mid-redeem): report what the ledger actually says, not what we
        # attempted. Never a silent overwrite of its verdict.
        current = await approval_ledger_repository.get_by_approval_id(approval_id)
        live = current if current is not None else row
        actual = live.standing
        log.error(
            f"{LogTag.HIL} Ticket receipt lost its CAS; reporting actual state",
            approval_id=approval_id,
            attempted=action.value,
            actual=actual,
        )
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            action=live.action,
            detail=f"Already {actual}; report that instead of retrying.",
        )
    await _settle_terminal(row, action)
    return RedeemResult(ok=result.ok, approval_id=approval_id, action=action, detail=detail)


async def _settle_terminal(row: ApprovalLedgerDocument, action: ActionResult) -> None:
    """Restate the approval with its action's result (executed/failed/unknown), so its card shows it."""
    await record_approved_action_ended(row.conversation_id, row.user_id, row.approval_id, action)


def _standing(decided: ApprovalDecided | None) -> str:
    """Name where a logged approval stands: its action's result, how it ended, or pending."""
    if decided is None:
        return "pending"
    return str(decided.action or decided.outcome)


async def _decide(
    row: ApprovalLedgerDocument,
    outcome: ApprovalOutcome,
    decider: ApprovalDecider | None,
    *,
    feedback: str | None = None,
) -> DecisionTaken:
    """Decide the approval in the log, then carry out whatever decision stands there.

    The hand-off is leased on the ledger row before the log is written, so a decision whose
    ledger write or hand-off fails is found by the sweeper and carried out from the log.
    An approval that expired or was let go with its work ends that way: then this decision was not taken.
    """
    now = datetime.now(UTC)
    leased = await approval_ledger_repository.claim_delivery(
        row.approval_id, now, DECISION_HANDOFF_LEASE
    )
    status = await logged_status(row.conversation_id, row.user_id, row.approval_id, now)
    # A yes or no counts only while the approval waits; one nobody can decide ends as its status says.
    let_go = _LET_GO.get(status) if outcome in DECIDED_OUTCOMES else None
    taken = await record_approval_decided(
        row.conversation_id,
        row.user_id,
        row.approval_id,
        outcome if let_go is None else let_go,
        decider if let_go is None else None,
        feedback=feedback if let_go is None else None,
    )
    if leased is not None:
        await _carry_out(leased, taken.stands, now)
    return DecisionTaken(stands=taken.stands, taken=taken.taken and taken.stands.outcome is outcome)


async def _carry_out(
    leased: ApprovalLedgerDocument, stands: ApprovalDecided, since: datetime
) -> None:
    """Bring the row leased at since to the decision the log holds, hand that decision to the work, end the lease.

    The ledger follows the log: a row holding another outcome has drifted from it, a bug said loudly.
    """
    if leased.outcome is None:
        decided_by = leased.user_id if stands.decider is ApprovalDecider.USER else None
        if not await approval_ledger_repository.settle(
            leased.approval_id, stands.outcome, decided_by=decided_by, feedback=stands.feedback
        ):
            raise LedgerDriftError(leased.approval_id, stands.outcome)
        leased.outcome, leased.feedback = stands.outcome, stands.feedback
    elif leased.outcome is not stands.outcome:
        raise LedgerDriftError(leased.approval_id, stands.outcome)
    if stands.action is None:
        await _hand_off(leased, stands)
    await approval_ledger_repository.finish_delivery(leased.approval_id, since)


async def _hand_off(row: ApprovalLedgerDocument, stands: ApprovalDecided) -> None:
    """Tell the work waiting on the approval how it was decided; a failed hand-off raises and is retried.

    A withdrawn or cancelled approval has nothing waiting on it: the agent withdrew it, or the user stopped the work.
    """
    match stands.outcome:
        case ApprovalOutcome.APPROVED if row.owner_run_type:
            # A background owner has no live run: its resume carries the ticket.
            await resume_owner_after_approval(row, stands)
        case ApprovalOutcome.APPROVED:
            await _deliver_ticket(row, stands)
        case ApprovalOutcome.DENIED:
            if stands.feedback is not None:
                # A no that asks for something else is work: delivery starts a run when none is live.
                await _deliver_verdict(row, ApprovalOutcome.DENIED, stands.feedback)
            else:
                # A plain no is final and its surface already said so: only a live run needs telling.
                await _wake_agent(row, ApprovalOutcome.DENIED, None)
            # A background todo has no other surface: leave the skip in its log.
            await record_owner_deny(row, stands.feedback)
        case ApprovalOutcome.EXPIRED:
            await _deliver_verdict(row, ApprovalOutcome.EXPIRED, None)


async def hand_off_stale_decision(row: ApprovalLedgerDocument, now: datetime) -> bool:
    """Carry out a decision whose hand-off began over a lease ago and never finished; False when none was due.

    A lease with no decision in the log is a decide whose log write failed: nothing was decided.
    """
    leased = await approval_ledger_repository.claim_delivery(
        row.approval_id, now, DECISION_HANDOFF_LEASE
    )
    if leased is None:
        return False
    stands = await logged_decision(leased.conversation_id, leased.user_id, leased.approval_id)
    if stands is None:
        await approval_ledger_repository.finish_delivery(leased.approval_id, now)
        return False
    await _carry_out(leased, stands, now)
    return True


def _capture_revoked(row: ApprovalLedgerDocument, revoker: str, outcome: UndecidedOutcome) -> None:
    capture(
        UserId(row.user_id),
        HilRevoked(
            approval_id=row.approval_id,
            ledger_version=row.v + 1,
            revoker=revoker,
            outcome=outcome,
        ),
    )


async def revoke_ticket(
    approval_id: str, *, user_id: str, conversation_id: str, caller: str
) -> str:
    """Withdraw your own pending approval.

    The revoke half of the ticket convention (mirrors redeem_approved): the
    row ends withdrawn; decided rows are untouchable, so report those
    instead. Unknown ids and foreign conversations read identically —
    existence must not leak across conversations.
    """

    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is None or row.conversation_id != conversation_id:
        return f"No pending approval with id '{approval_id}'."
    if row.user_id != user_id:
        raise ApprovalRequestForbiddenError()
    if caller != row.owner_agent and not caller.startswith(EXECUTOR_THREAD_PREFIX):
        return (
            f"Cannot revoke '{approval_id}': it belongs to another worker. "
            "Only its proposer or the executor can withdraw it."
        )
    taken = await _decide(row, ApprovalOutcome.WITHDRAWN, None)
    if not taken.taken:
        return (
            f"Cannot revoke '{approval_id}': already {_standing(taken.stands)}. "
            "Report that to the user instead of retrying."
        )
    _capture_revoked(row, caller, ApprovalOutcome.WITHDRAWN)
    return f"Revoked '{approval_id}' ({row.summary}). It will never be asked."


async def cancel_ledger_approvals(
    conversation_id: str,
    user_id: str,
    approval_ids: Collection[str],
    outcome: UndecidedOutcome = ApprovalOutcome.CANCELLED,
) -> list[str]:
    """End these approvals undecided in the log, so a later Approve (a stale card, a bot "yes") finds them closed.

    Only approvals still pending in the log close; a decided one keeps its decision.
    """
    cancelled: list[str] = []
    for approval_id in sorted(approval_ids):
        row = await approval_ledger_repository.get_by_approval_id(approval_id)
        if row is None or row.conversation_id != conversation_id or row.user_id != user_id:
            continue
        if not (await _decide(row, outcome, None)).taken:
            continue
        _capture_revoked(row, "cancelled-run", outcome)
        cancelled.append(row.approval_id)
    if cancelled:
        log.info(
            f"{LogTag.HIL} Cancelled pending ledger approvals for a stopped run",
            conversation_id=conversation_id,
            approval_ids=cancelled,
        )
    return cancelled


async def expire_ledger_approval(row: ApprovalLedgerDocument) -> bool:
    """Expire an approval nobody decided in time and tell the work waiting on it; False when a decision beat this one.

    Expiry is a decision like any other: the log takes it once, and the work resumes with it.
    """
    if not (await _decide(row, ApprovalOutcome.EXPIRED, None)).taken:
        return False
    _capture_revoked(row, "expired", ApprovalOutcome.EXPIRED)
    return True


async def end_unledgered_approval(
    conversation_id: str,
    user_id: str,
    requested: ApprovalRequested,
    outcome: Literal[ApprovalOutcome.EXPIRED, ApprovalOutcome.WITHDRAWN],
) -> bool:
    """End an approval whose request never reached the ledger and tell the work waiting on it; False when a decision beat this one.

    Decided like expiry: the log takes it once and the work resumes with it, so nothing else ends that work.
    """
    approval_id = requested.approval_id
    if not (
        await record_approval_decided(conversation_id, user_id, approval_id, outcome, None)
    ).taken:
        return False
    summary = requested.description.action
    await _deliver_verdict_task(
        conversation_id,
        user_id,
        _verdict_task(approval_id, summary, outcome, None),
        requested.task_id,
    )
    return True


async def reconcile_conversation_ledger(conversation_id: str) -> None:
    """Heal one conversation's ledger as a decide-path side effect.

    Nothing else watches a running action, so every decide repairs: a stalled executing
    action goes unknown (with a wake). A decision whose hand-off failed is the sweeper's
    (hand_off_stale_decision). Every step is CAS-guarded, so concurrent deciders converge.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=STALLED_EXECUTING_MINUTES)
    for stalled in await approval_ledger_repository.list_stalled_executing(cutoff, conversation_id):
        if await approval_ledger_repository.finish_action(
            stalled.approval_id, ActionResult.UNKNOWN
        ):
            log.error(
                f"{LogTag.HIL} Ledger execution stalled; reconciled as UNKNOWN, never retried",
                approval_id=stalled.approval_id,
            )
            await _settle_terminal(stalled, ActionResult.UNKNOWN)
            await _wake_agent(
                stalled,
                "UNKNOWN",
                "stalled execution reconciled; never retried. The action may or may not "
                "have run — verify before re-proposing, never blind-retry.",
            )


async def _wake_agent(row: ApprovalLedgerDocument, outcome: str, result: object) -> None:
    """One DECISIONS line into the executor inbox; a missing Redis or a failed append raises.

    Inbox is transport, ledger is truth: a lost wake re-surfaces via the next
    OPEN PENDINGS injection, never via re-execution.
    """
    if redis_cache.client is None:
        raise LedgerWakeUndeliveredError(row.approval_id, outcome)
    preview = "" if result is None else str(result)[:500]
    await ExecutorInbox(row.conversation_id).append(
        str(uuid4()),
        f"DECISIONS: {row.approval_id}={outcome} {row.summary}"
        + (f" :: {preview}" if preview else ""),
        AgentTag.HIL_DECISION,
    )
