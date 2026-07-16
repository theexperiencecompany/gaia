"""Resolve pending HIL approvals from the user's next chat message.

When a conversation has approvals waiting and the user simply replies in chat
(instead of clicking a button), one fast LLM call classifies the reply.
Approve/deny resolves the approval(s) and resumes the paused run; an unrelated
message abandons them (resumed as refusals, so the run wraps up instead of
racing the new turn) and lets the new turn run normally.

With several approvals pending (a wait_for_subagents batch), the reply is
classified per item against the numbered list: "yes" approves all, "just the
email" approves one and leaves the rest pending, "no" declines all. This is the
only decision surface a text-only channel (WhatsApp/Telegram) has — buttons
exist only on web/mobile. An item the reply doesn't address stays pending for
the buttons or the timeout sweep.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalRecord
from app.services.hil.approvals_store import list_pending_for_conversation
from app.services.hil.resolution import (
    ApprovalRequestForbidden,
    ApprovalRequestNotFound,
    abandon_conversation_approvals,
    resolve_approval,
)
from shared.py.wide_events import log

DecisionAction = Literal["approve", "deny", "unrelated"]

# Auto-deny reason when the user moves on without answering the approval.
UNRELATED_FEEDBACK = "The user moved on to a different request; do not perform the action."


class DecisionResult(BaseModel):
    """LLM classification of a user's reply to a pending approval."""

    action: DecisionAction
    feedback: str | None = None


class BatchItemDecision(BaseModel):
    """One pending action's verdict from the user's reply."""

    index: int = Field(description="1-based index of the pending action")
    action: Literal["approve", "deny", "leave"]
    feedback: str | None = None


class BatchDecisionResult(BaseModel):
    """LLM classification of a reply against several pending approvals."""

    unrelated: bool = Field(
        description="True when the message is a new request, not an answer to the pending actions"
    )
    decisions: list[BatchItemDecision] = Field(default_factory=list)


async def resolve_pending_from_message(
    conversation_id: str, user_id: str, message: str
) -> DecisionAction | None:
    """Resolve the conversation's pending approval(s) from ``message``.

    Returns the overall classified action ("approve" when anything was approved,
    "deny" when things were only declined, "unrelated" when the user moved on),
    or ``None`` when nothing was pending or the reply addressed none of it.
    """
    pending = await list_pending_for_conversation(conversation_id)
    if not pending:
        return None
    if len(pending) == 1:
        return await _resolve_single(pending[0], conversation_id, user_id, message)
    return await _resolve_batch(pending, conversation_id, user_id, message)


async def _resolve_single(
    record: HILApprovalRecord, conversation_id: str, user_id: str, message: str
) -> DecisionAction | None:
    result = await interpret_decision_message(message, [record.summary])
    if result.action == "unrelated":
        # The user moved on. Abandon the paused run so it resumes, sees a refusal,
        # wraps up, and frees the conversation's executor lock for the new turn.
        await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    await _safe_resolve(record.approval_id, user_id, result.action, result.feedback)
    return result.action


async def _resolve_batch(
    pending: list[HILApprovalRecord], conversation_id: str, user_id: str, message: str
) -> DecisionAction | None:
    """Apply a per-item classification of ``message`` to the pending batch.

    Decisions dispatch through ``resolve_approval`` one by one; the per-conversation
    resume slot ensures only the first actually re-dispatches the executor — the
    join round it wakes collects the rest.
    """
    result = await interpret_batch_decision_message(message, [r.summary for r in pending])
    if result.unrelated:
        await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    approved = denied = 0
    for decision in result.decisions:
        if decision.action == "leave" or not 1 <= decision.index <= len(pending):
            continue
        record = pending[decision.index - 1]
        await _safe_resolve(record.approval_id, user_id, decision.action, decision.feedback)
        if decision.action == "approve":
            approved += 1
        else:
            denied += 1

    if approved:
        return "approve"
    if denied:
        return "deny"
    return None


async def interpret_batch_decision_message(
    message: str, pending_summaries: list[str]
) -> BatchDecisionResult:
    """Classify a chat reply against several pending approvals, per item.

    Fails toward leaving everything pending (empty decisions, not unrelated) —
    never toward acting, and never toward abandoning on an LLM hiccup.
    """
    try:
        return await ainvoke_structured(
            BatchDecisionResult,
            _batch_prompt(message, pending_summaries),
            label="hil_conversational_resolve_batch",
        )
    except Exception as e:
        log.warning(f"{LogTag.HIL} Batch conversational resolve failed, leaving pending: {e}")
        return BatchDecisionResult(unrelated=False)


async def interpret_decision_message(message: str, pending_summaries: list[str]) -> DecisionResult:
    """Classify a chat reply against pending approvals. Fails toward ``unrelated``
    (normal chat), never toward silently executing an action."""
    try:
        return await ainvoke_structured(
            DecisionResult,
            _prompt(message, pending_summaries),
            label="hil_conversational_resolve",
        )
    except Exception as e:
        log.warning(f"{LogTag.HIL} Conversational resolve failed, treating as unrelated: {e}")
        return DecisionResult(action="unrelated")


# --- internals -----------------------------------------------------------------


async def _safe_resolve(
    approval_id: str, user_id: str, decision: Literal["approve", "deny"], feedback: str | None
) -> None:
    """Apply one decision, tolerating an already-resolved/expired approval."""
    try:
        await resolve_approval(
            approval_id=approval_id,
            user_id=user_id,
            kind=decision,
            feedback=feedback,
            scope="once",
        )
    except (ApprovalRequestNotFound, ApprovalRequestForbidden):
        pass


def _prompt(message: str, pending_summaries: list[str]) -> str:
    actions = "\n".join(f"- {summary}" for summary in pending_summaries)
    return (
        "The assistant is waiting for the user to approve or decline these "
        "pending actions:\n"
        f"{actions}\n\n"
        f"The user just sent this message:\n{message!r}\n\n"
        "Is the user approving those actions, declining them, or making an "
        "unrelated new request? Reply with action='approve', 'deny', or "
        "'unrelated', and extract any feedback or conditions they gave."
    )


def _batch_prompt(message: str, pending_summaries: list[str]) -> str:
    actions = "\n".join(
        f"{index}. {summary}" for index, summary in enumerate(pending_summaries, start=1)
    )
    return (
        "The assistant is waiting for the user to approve or decline these "
        "numbered pending actions:\n"
        f"{actions}\n\n"
        f"The user just sent this message:\n{message!r}\n\n"
        "Decide per action. A blanket answer applies to all of them: a plain "
        "'yes'/'go ahead' approves every action, a plain 'no'/'don't' declines "
        "every action. A selective answer ('just the email', 'skip slack', "
        "'approve 1 but not 2') applies only to the actions it names — mark each "
        "named one approve/deny and every unmentioned one 'leave'. If the "
        "message asks a question about the actions or is otherwise not a "
        "decision on any of them, mark all 'leave'. Set unrelated=true ONLY "
        "when the message is clearly a new, different request that ignores the "
        "pending actions. Extract any feedback or conditions per action."
    )
