"""Resolve a pending HIL approval from the user's next chat message.

When a conversation has a single approval waiting and the user simply replies in
chat (instead of clicking a button), one fast LLM call classifies the reply as
approving, declining, or an unrelated new request. Approve/deny relays the
decision to the awaiting gate; an unrelated message abandons the parked run (so
the gate never hangs and the run never races the new turn) and lets the new turn
run normally.

Chat resolution only fires when exactly one approval is pending: a single
"yes"/"no" cannot say which of several concurrent approvals it means, so with
more than one in flight this defers to the per-card approve/decline buttons.
"""

from typing import Literal

from pydantic import BaseModel

from app.agents.llm.client import ainvoke_structured
from app.constants.log_tags import LogTag
from app.services.hil.bridge import (
    ApprovalRequestForbidden,
    ApprovalRequestNotFound,
    abandon_pending_run,
    pending_approvals_for_conversation,
    relay_approval_decision,
)
from shared.py.wide_events import log

DecisionAction = Literal["approve", "deny", "unrelated"]

# Auto-deny reason when the user moves on without answering the approval.
UNRELATED_FEEDBACK = "The user moved on to a different request; do not perform the action."


class DecisionResult(BaseModel):
    """LLM classification of a user's reply to a pending approval."""

    action: DecisionAction
    feedback: str | None = None


async def resolve_pending_from_message(
    conversation_id: str, user_id: str, message: str
) -> DecisionAction | None:
    """Resolve a lone pending approval in the conversation from ``message``.

    Returns the classified action, or ``None`` when zero — or more than one —
    approvals are pending. With several in flight a single reply can't say which
    it means, so those are left for the per-card buttons rather than guessed at.
    """
    pending = await pending_approvals_for_conversation(conversation_id)
    if len(pending) != 1:
        return None

    item = pending[0]
    result = await interpret_decision_message(message, [item.get("summary", "")])
    if result.action == "unrelated":
        # The user moved on. Abandon the parked run (cancel it, don't deny-and-
        # resume) so it can't race the new turn about to run for this message.
        await abandon_pending_run(
            item["approval_id"], user_id, item.get("stream_id", ""), UNRELATED_FEEDBACK
        )
        return "unrelated"

    await _safe_relay(item["approval_id"], user_id, result.action, result.feedback)
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


async def _safe_relay(approval_id: str, user_id: str, decision: str, feedback: str | None) -> None:
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
