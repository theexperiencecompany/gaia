"""Resolve pending HIL approvals from a bot user's next chat reply.

BUTTON-LESS CHANNELS ONLY: the caller (_resolve_pending_approval_turn in
app/services/chat/stream.py) invokes this for messaging-platform bots alone;
web/mobile/desktop resolve via POST /approvals/{id}/decision instead.

A reply approves (runs EXACTLY as proposed), denies (any change is a deny with
the change as feedback), or is unrelated (abandon, run the new message). Several
pending approvals decide per item: unnamed items deny on an exclusive reply and
stay pending on a partial one. JEV (jev_reply.py) classifies first when the
user's flag is on, the LLM on its transport failure. Fails safe: a classifier
error leaves approvals pending, never approves.
"""

import contextlib
from typing import Literal, assert_never

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, silent_metered_config
from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
    HIL_LLM_TIMEOUT_SECONDS,
    UNRELATED_FEEDBACK,
    ReplyChoice,
)
from app.constants.log_tags import LogTag
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.hil_models import (
    ApprovalLedgerDocument,
    BatchDecisionResult,
    BatchItemDecision,
    DecisionAction,
    DecisionResult,
    HILApprovalRecord,
    LedgerState,
)
from app.models.message_models import MessageDict
from app.services.feature_flags import is_jev_reply_enabled
from app.services.hil.approvals_store import list_pending_for_conversation
from app.services.hil.bridge import build_action_detail
from app.services.hil.jev_reply import ask_jev_reply, settle_reply
from app.services.hil.ledger_decide import LedgerDecision, decide_ledger
from app.services.hil.prompts import (
    CONVERSATIONAL_BATCH_PROMPT,
    CONVERSATIONAL_CONTEXT_BLOCK,
    CONVERSATIONAL_REPLY_PROMPT,
)
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
    abandon_conversation_approvals,
    resolve_approval,
)
from app.utils.general_utils import clip_text
from shared.py.wide_events import log

# Ground truth for a settled ledger row in the bot reply's words. Lives here, not
# result_delivery (which only knows barrier statuses), so the bot path can narrate
# executed/failed/unknown/revoked without depending on that module.
LEDGER_OUTCOME_TEXT: dict[LedgerState, str] = {
    LedgerState.APPROVED: "approved by the user; the agent runs it from the ticket",
    LedgerState.DENIED: "denied by the user; the action did NOT run",
    LedgerState.EXECUTED: "approved by the user and executed",
    LedgerState.FAILED: "approved by the user but execution failed",
    LedgerState.UNKNOWN: "approved by the user but the outcome is unknown; never retried",
    LedgerState.REVOKED: "withdrawn by the agent; the action did NOT run",
}


def ledger_outcome_text(state: LedgerState) -> str:
    """One line of ground truth for a settled ledger row."""
    return LEDGER_OUTCOME_TEXT.get(state, state.value)


async def resolve_pending_from_message(
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None = None,
) -> DecisionAction | None:
    """Resolve the conversation's pending approval(s) from message.

    history is a recent window of prior turns (context for the classifier).
    Returns the overall classified action ("approve" when anything was approved,
    "deny" when things were only declined, "unrelated" when the user moved on),
    or None when nothing was pending or the reply addressed none of it.
    """
    pending = await list_pending_for_conversation(conversation_id)
    if pending:
        if len(pending) == 1:
            return await _resolve_single(pending[0], conversation_id, user_id, message, history)
        return await _resolve_batch(pending, conversation_id, user_id, message, history)
    # Barrier store empty: ledger-enabled users' rows live in approval_ledger.
    ledger_pending = await _list_pending_ledger(conversation_id)
    if not ledger_pending:
        return None
    if len(ledger_pending) == 1:
        return await _resolve_single(ledger_pending[0], conversation_id, user_id, message, history)
    return await _resolve_batch(ledger_pending, conversation_id, user_id, message, history)


async def _resolve_single(
    record: HILApprovalRecord | ApprovalLedgerDocument,
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None,
) -> DecisionAction | None:
    action_detail = build_action_detail(record.summary, record.args)
    result = await interpret_decision_message(message, action_detail, history, user_id=user_id)
    if result is None:
        # The classifier errored. Leave the approval pending rather than abandon it —
        # a transient hiccup must not silently decline a legitimate pending action
        # (matches the batch path's fail-toward-pending behavior).
        return None
    if result.action == "unrelated":
        # The user moved on. Abandon the paused run so it resumes, sees a refusal,
        # wraps up, and frees the conversation's executor lock for the new turn.
        if isinstance(record, ApprovalLedgerDocument):
            await _abandon_ledger_approvals(conversation_id, user_id)
        else:
            await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    action, feedback = no_arg_edit(result.action, result.feedback)
    if isinstance(record, ApprovalLedgerDocument):
        await _safe_resolve_ledger(record.approval_id, user_id, action, feedback)
    else:
        await _safe_resolve(record.approval_id, user_id, action, feedback)
    return action


async def _resolve_batch(
    pending: list[HILApprovalRecord] | list[ApprovalLedgerDocument],
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None,
) -> DecisionAction | None:
    """Apply a per-item classification of message to the pending batch.

    Decisions dispatch through resolve_approval (barrier) or decide_ledger
    (ledger) one by one; the per-conversation resume slot ensures only the first
    actually re-dispatches the executor — the join round it wakes collects the rest.
    """
    action_details = [build_action_detail(r.summary, r.args) for r in pending]
    result = await interpret_batch_decision_message(
        message, action_details, history, user_id=user_id
    )
    if result.unrelated:
        if pending and isinstance(pending[0], ApprovalLedgerDocument):
            await _abandon_ledger_approvals(conversation_id, user_id)
        else:
            await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    approved, denied = await _apply_decisions(pending, user_id, result.decisions)
    if approved:
        return "approve"
    if denied:
        return "deny"
    return None


async def _apply_decisions(
    pending: list[HILApprovalRecord] | list[ApprovalLedgerDocument],
    user_id: str,
    decisions: list[BatchItemDecision],
) -> tuple[int, int]:
    """Dispatch every in-range decision onto its pending item; returns (approved, denied)."""
    approved = denied = 0
    for decision in decisions:
        if decision.action == "leave" or not 1 <= decision.index <= len(pending):
            continue
        record = pending[decision.index - 1]
        action, feedback = no_arg_edit(decision.action, decision.feedback)
        if isinstance(record, ApprovalLedgerDocument):
            await _safe_resolve_ledger(record.approval_id, user_id, action, feedback)
        else:
            await _safe_resolve(record.approval_id, user_id, action, feedback)
        if action == "approve":
            approved += 1
        else:
            denied += 1
    return approved, denied


async def interpret_batch_decision_message(
    message: str,
    action_details: list[str],
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> BatchDecisionResult:
    """Classify a chat reply against several pending approvals, per item.

    JEV first when the user's flag is on; its failure falls back to the LLM.
    """
    if await is_jev_reply_enabled(user_id):
        try:
            verdicts, _in, _out = await ask_jev_reply(message, action_details, history)
        except Exception as e:
            _log_jev_fallback(e)
        else:
            return batch_from_jev_reply(settle_reply(verdicts), message)
    return await classify_batch_with_llm(message, action_details, history, user_id=user_id)


async def interpret_decision_message(
    message: str,
    action_detail: str,
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> DecisionResult | None:
    """Classify a chat reply against one pending approval; None leaves it pending.

    JEV first when the user's flag is on; its failure falls back to the LLM.
    """
    if await is_jev_reply_enabled(user_id):
        try:
            verdicts, _in, _out = await ask_jev_reply(message, [action_detail], history)
        except Exception as e:
            _log_jev_fallback(e)
        else:
            return decision_from_jev_reply(settle_reply(verdicts)[0], message)
    return await classify_with_llm(message, action_detail, history, user_id=user_id)


def decision_from_jev_reply(choice: ReplyChoice, message: str) -> DecisionResult | None:
    """Map one settled JEV choice onto the single-approval result; leave is None.

    A deny carries the reply verbatim: JEV returns no text, and the user's own
    words are the correction the agent needs.
    """
    match choice:
        case ReplyChoice.APPROVE:
            return DecisionResult(action="approve")
        case ReplyChoice.DENY:
            return DecisionResult(action="deny", feedback=message)
        case ReplyChoice.UNRELATED:
            return DecisionResult(action="unrelated")
        case ReplyChoice.LEAVE:
            return None
        case _:
            assert_never(choice)


def batch_from_jev_reply(choices: list[ReplyChoice], message: str) -> BatchDecisionResult:
    """Map settled JEV choices onto the per-item batch result (1-based indexes)."""
    if all(choice is ReplyChoice.UNRELATED for choice in choices):
        return BatchDecisionResult(unrelated=True)
    decisions = []
    for index, choice in enumerate(choices, start=1):
        match choice:
            case ReplyChoice.APPROVE:
                decisions.append(BatchItemDecision(index=index, action="approve"))
            case ReplyChoice.DENY:
                decisions.append(BatchItemDecision(index=index, action="deny", feedback=message))
            case ReplyChoice.LEAVE | ReplyChoice.UNRELATED:
                decisions.append(BatchItemDecision(index=index, action="leave"))
            case _:
                assert_never(choice)
    return BatchDecisionResult(unrelated=False, decisions=decisions)


async def classify_batch_with_llm(
    message: str,
    action_details: list[str],
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> BatchDecisionResult:
    """LLM per-item classification of a reply against several pending approvals.

    Fails toward leaving everything pending (empty decisions, not unrelated) —
    never toward acting, and never toward abandoning on an LLM hiccup.
    """
    try:
        return await ainvoke_structured(
            BatchDecisionResult,
            _batch_prompt(message, action_details, history),
            label="hil_conversational_resolve_batch",
            config=silent_metered_config(user_id),
            options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Batch conversational resolve failed, leaving pending",
            error=str(e),
            error_type=type(e).__name__,
        )
        return BatchDecisionResult(unrelated=False)


async def classify_with_llm(
    message: str,
    action_detail: str,
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> DecisionResult | None:
    """LLM classification of a reply against one pending approval.

    None on an LLM error, so the caller leaves the approval pending — never toward
    silently executing an action, and never toward abandoning a legitimate one on a
    transient hiccup (an error is not the same signal as a genuine unrelated)."""
    try:
        return await ainvoke_structured(
            DecisionResult,
            _prompt(message, action_detail, history),
            label="hil_conversational_resolve",
            config=silent_metered_config(user_id),
            options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Conversational resolve failed, leaving pending",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


def no_arg_edit(
    action: Literal["approve", "deny"], feedback: str | None
) -> tuple[Literal["approve", "deny"], str | None]:
    """Turn an 'approve' carrying feedback into a deny, since there is no arg-editing.

    The gate runs the tool with its ORIGINAL args, so an 'approve' with feedback
    (e.g. "cc finance") would silently drop it. Declining with that feedback makes
    the agent re-propose with the change instead of running the wrong action.
    """
    if action == "approve" and (feedback or "").strip():
        return "deny", feedback
    return action, feedback


# --- internals -----------------------------------------------------------------


def _log_jev_fallback(error: Exception) -> None:
    log.warning(
        f"{LogTag.HIL} JEV reply classifier failed; falling back to the LLM classifier",
        error=str(error),
        error_type=type(error).__name__,
    )


async def _safe_resolve(
    approval_id: str, user_id: str, decision: Literal["approve", "deny"], feedback: str | None
) -> None:
    """Apply one decision, tolerating an already-resolved/expired approval."""
    with contextlib.suppress(ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
        await resolve_approval(
            approval_id=approval_id,
            user_id=user_id,
            kind=decision,
            feedback=feedback,
            scope="once",
        )


async def _list_pending_ledger(conversation_id: str) -> list[ApprovalLedgerDocument]:
    """Ledger-enabled users' decidable rows: list_open covers live states, only PENDING decides here."""
    return [
        row
        for row in await approval_ledger_repository.list_open(conversation_id)
        if row.state is LedgerState.PENDING
    ]


async def _safe_resolve_ledger(
    approval_id: str, user_id: str, decision: Literal["approve", "deny"], feedback: str | None
) -> None:
    """Apply one ledger decision, tolerating a lost race.

    Bots carry no row version, so v=None — the PENDING->decided CAS inside
    decide_ledger still guards.
    """
    result: LedgerDecision | None = None
    with contextlib.suppress(ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
        result = await decide_ledger(
            approval_id, user_id=user_id, kind=decision, feedback=feedback, v=None
        )
    if result is not None and not result.committed:
        log.warning(
            f"{LogTag.HIL} Ledger bot decision lost the race",
            approval_id=approval_id,
            state=result.state.value,
            outcome=ledger_outcome_text(result.state),
        )


async def _abandon_ledger_approvals(conversation_id: str, user_id: str) -> None:
    """Deny every pending ledger row because the user moved on.

    Denies with the moved-on feedback, which wakes the agent to wrap up.
    """
    for row in await _list_pending_ledger(conversation_id):
        with contextlib.suppress(ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
            await decide_ledger(
                row.approval_id, user_id=user_id, kind="deny", feedback=UNRELATED_FEEDBACK, v=None
            )


def _history_block(history: list[MessageDict] | None) -> str:
    """Recent turns as role: content lines, per-turn and total bounded."""
    if not history:
        return ""
    lines = [
        f"{turn.get('role', '')}: {clip_text(turn.get('content') or '', HIL_CLASSIFIER_MAX_ARG_CHARS)}"
        for turn in history
    ]
    return clip_text("\n".join(lines), HIL_CLASSIFIER_MAX_DETAIL_CHARS)


def _context(history: list[MessageDict] | None) -> str:
    history_block = _history_block(history)
    return CONVERSATIONAL_CONTEXT_BLOCK.format(history=history_block) if history_block else ""


def _prompt(message: str, action_detail: str, history: list[MessageDict] | None) -> str:
    return CONVERSATIONAL_REPLY_PROMPT.format(
        action=action_detail, context=_context(history), message=message
    )


def _batch_prompt(
    message: str, action_details: list[str], history: list[MessageDict] | None
) -> str:
    actions = "\n\n".join(
        f"{index}. {detail}" for index, detail in enumerate(action_details, start=1)
    )
    return CONVERSATIONAL_BATCH_PROMPT.format(
        actions=actions, context=_context(history), message=message
    )
