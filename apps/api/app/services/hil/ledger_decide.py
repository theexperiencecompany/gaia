"""Decide approvals in the conversation log, wake the agent with the ticket, and redeem it.

The single entry point for every decision source (card, batch review, a chat reply).
Approval is permission, not execution: committing wakes the model with the ticket
(the approval id), and the model redeems it with execute(tool_name="approve",
data={"id": ...}), which runs the envelope the ledger stored for it.

The log is the approval's only truth: a decision is an ApprovalDecided append, and
the first one wins, so a double tap or a tap on an expired or stopped approval reads
back the decision already logged. The ledger follows the log, as the fingerprint
index and the envelope; its action claim keeps a redeem single-use, and crash
recovery runs lazily via reconcile_conversation_ledger; the conversation sweeper
expires approvals nobody decided.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.tools.execute.dispatch import (
    dispatch_config_for,
    dispatch_tool,
)
from app.constants.agents import AgentTag
from app.constants.general import EXECUTOR_THREAD_PREFIX
from app.constants.hil import ApprovalDecision
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.conversation_log_models import ApprovalDecided
from app.models.execute_models import DispatchErrorKind
from app.models.hil_models import ApprovalLedgerDocument
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import (
    ApprovalDecisionRequest,
    BatchDecisionItem,
    BatchDecisionOutcome,
)
from app.services.analytics_service import capture
from app.services.conversation.work_log import (
    DecisionTaken,
    logged_decision,
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
from app.services.hil.ticket import approval_ticket
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import (
    ApprovalDecided as ApprovalDecidedEvent,
    HilDecisionSubmitted,
    HilDecisionVia,
    HilRevoked,
)
from shared.py.approvals import (
    ActionResult,
    ApprovalDecider,
    ApprovalOutcome,
    DecidedOutcome,
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
    if tap.scope == "always_tool" and await asks_every_time(row.tool_name, row.args):
        raise ToolAlwaysAsksError()
    decision = await _commit_decision(
        row, user_id=user_id, kind=tap.decision, feedback=tap.feedback, via="card"
    )
    if (
        tap.scope == "always_tool"
        and decision.committed
        and decision.outcome is ApprovalOutcome.APPROVED
    ):
        tool_key = row.tool_key or await resolved_tool_key(user_id, row.tool_name)
        await set_tool_override(user_id, tool_key, False)
    return decision


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
    # Approve+feedback is a conditional approval, but envelopes carry no
    # conditions: route it to deny (as the chat classifier does) so nothing
    # runs beyond the granted permission; the note is attached to the denial.
    if kind == "approve" and feedback is not None and feedback.strip() != "":
        kind = "deny"

    target: DecidedOutcome = (
        ApprovalOutcome.APPROVED if kind == "approve" else ApprovalOutcome.DENIED
    )
    taken = await _decide_in_log(row, target, ApprovalDecider.USER, feedback=feedback)
    if not taken.taken:
        return LedgerDecision(
            committed=False,
            approval_id=approval_id,
            outcome=taken.stands.outcome,
            action=taken.stands.action,
        )
    await _follow_in_ledger(row, target, decided_by=user_id, feedback=feedback)

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
    if target is ApprovalOutcome.APPROVED:
        # One continuation: a background owner's resume carries the ticket; a live run gets it.
        if row.owner_run_type:
            await resume_owner_after_approval(row)
        else:
            await _deliver_ticket(row)
    else:
        # A wake alone reaches only a running run: delivery starts one to report what was skipped.
        await _deliver_verdict(row, "DENIED", feedback)
        # A background todo has no other surface: leave the skip in its log.
        await record_owner_deny(row, feedback)
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
                    reason="not_found",
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


async def _deliver_ticket(row: ApprovalLedgerDocument) -> None:
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
        approval_ticket(row),
    )


async def _deliver_verdict(row: ApprovalLedgerDocument, outcome: str, result: object) -> None:
    """Steer or start a run with a non-approve verdict (deny today); a failed delivery raises to the tap."""
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
    await deliver_to_executor(row.conversation_id, AuthenticatedUser(user_id=row.user_id), task)


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
    if decided is None or decided.outcome is not ApprovalOutcome.APPROVED or decided.action:
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            action=None if decided is None else decided.action,
            detail=f"Already {_standing(decided)}; report that instead of retrying.",
        )
    if caller != row.owner_agent and not caller.startswith(EXECUTOR_THREAD_PREFIX):
        return RedeemResult(
            ok=False,
            approval_id=approval_id,
            action=row.action,
            detail="This ticket belongs to another worker; only its proposer or the executor may redeem it.",
        )
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


async def _decide_in_log(
    row: ApprovalLedgerDocument,
    outcome: ApprovalOutcome,
    decider: ApprovalDecider | None,
    *,
    feedback: str | None = None,
) -> DecisionTaken:
    """Decide the approval in the log; the decision that stands there is the approval's truth."""
    return await record_approval_decided(
        row.conversation_id, row.user_id, row.approval_id, outcome, decider, feedback=feedback
    )


async def _follow_in_ledger(
    row: ApprovalLedgerDocument,
    outcome: ApprovalOutcome,
    *,
    decided_by: str | None = None,
    feedback: str | None = None,
) -> None:
    """Bring the ledger row to the decision the log took, so its index and claim follow it.

    The log takes one decision per approval and every writer goes through it first, so a
    ledger row that is no longer pending here has drifted from the log: a bug, said loudly.
    """
    if not await approval_ledger_repository.settle(
        row.approval_id, outcome, decided_by=decided_by, feedback=feedback
    ):
        raise LedgerDriftError(row.approval_id, outcome)


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
    taken = await _decide_in_log(row, ApprovalOutcome.WITHDRAWN, None)
    if not taken.taken:
        return (
            f"Cannot revoke '{approval_id}': already {_standing(taken.stands)}. "
            "Report that to the user instead of retrying."
        )
    await _follow_in_ledger(row, ApprovalOutcome.WITHDRAWN)
    capture(
        UserId(user_id),
        HilRevoked(
            approval_id=approval_id,
            ledger_version=row.v + 1,
            revoker=caller,
            outcome=ApprovalOutcome.WITHDRAWN,
        ),
    )
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
        if not (await _decide_in_log(row, outcome, None)).taken:
            continue
        await _follow_in_ledger(row, outcome)
        capture(
            UserId(user_id),
            HilRevoked(
                approval_id=row.approval_id,
                ledger_version=row.v + 1,
                revoker="cancelled-run",
                outcome=outcome,
            ),
        )
        cancelled.append(row.approval_id)
    if cancelled:
        log.info(
            f"{LogTag.HIL} Cancelled pending ledger approvals for a stopped run",
            conversation_id=conversation_id,
            approval_ids=cancelled,
        )
    return cancelled


async def reconcile_conversation_ledger(conversation_id: str) -> None:
    """Heal one conversation's ledger as a decide-path side effect.

    Nothing else watches a running action, so every decide repairs: a stalled executing
    action goes unknown (with a wake). Orphaned approved rows need nothing — the
    ticket lives in model context and only a redeem runs the envelope. Every
    step is CAS-guarded, so concurrent deciders converge instead of duplicating.
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
