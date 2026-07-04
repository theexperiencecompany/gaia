"""Resolve a pending HIL approval from the user's next chat message.

When a conversation has an approval waiting and the user simply replies in chat
(instead of clicking a button), one fast LLM call classifies the reply as
approving, declining, or an unrelated new request. Approve/deny relays the
decision to the awaiting gate; an unrelated message auto-denies the pending
action (so the gate never hangs) and lets the new turn run normally.
"""

from typing import Literal

from pydantic import BaseModel

from app.agents.llm.client import ainvoke_structured
from app.constants.log_tags import LogTag
from app.services.hil.bridge import (
    ApprovalRequestForbidden,
    ApprovalRequestNotFound,
    pending_approvals_for_conversation,
    relay_approval_decision,
)
from shared.py.wide_events import log

DecisionAction = Literal["approve", "deny", "unrelated"]

# Auto-deny reason when the user moves on without answering the approval.
UNRELATED_FEEDBACK = "The user moved on to a different request; do not perform the action."


class DecisionResult(BaseModel):
    action: DecisionAction
    feedback: str | None = None


async def resolve_pending_from_message(
    conversation_id: str, user_id: str, message: str
) -> DecisionAction | None:
    """Resolve every pending approval in the conversation from ``message``.

    Returns the classified action, or ``None`` when nothing was pending. One
    reply applies to all pending approvals in the conversation — concurrent
    distinct approvals in one thread are rare and a single reply can't
    disambiguate them.
    """
    pending = await pending_approvals_for_conversation(conversation_id)
    if not pending:
        return None

    result = await interpret_decision_message(message, [p.get("summary", "") for p in pending])
    decision = "deny" if result.action != "approve" else "approve"
    feedback = UNRELATED_FEEDBACK if result.action == "unrelated" else result.feedback
    for item in pending:
        await _safe_relay(item["approval_id"], user_id, decision, feedback)
    return result.action


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


async def _safe_relay(
    approval_id: str, user_id: str, decision: str, feedback: str | None
) -> None:
    """Relay one decision, tolerating an already-resolved/expired approval."""
    try:
        await relay_approval_decision(
            approval_id=approval_id,
            user_id=user_id,
            decision=decision,
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
