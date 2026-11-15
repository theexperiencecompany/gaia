"""The ApprovalReplies port over the HIL reply classifier, for button-less surfaces."""

from app.constants.hil import (
    HIL_ACK_APPROVED,
    HIL_ACK_APPROVED_ONE,
    HIL_ACK_DENIED,
    HIL_ACK_DENIED_ONE,
)
from app.models.message_models import MessageDict
from app.services.hil.conversational import (
    ApprovalReplyOutcome,
    classifier_history,
    resolve_pending_from_message,
)
from app.services.hil.describe import describe_call


class HilApprovalReplies:
    """Resolves a typed reply against the conversation's pending approvals, each with its own decision."""

    async def resolve(
        self, conversation_id: str, user_id: str, message_text: str, history: list[MessageDict]
    ) -> str | None:
        """Return the acknowledgement of what the reply decided; None when it decided nothing.

        Each decided approval logs its own ApprovalDecided as the HIL resolution records it. A
        failure propagates: a retry re-reads what is still pending, so nothing is decided twice.
        """
        outcome = await resolve_pending_from_message(
            conversation_id, user_id, message_text, classifier_history(history)
        )
        if outcome is None or outcome.action == "unrelated":
            return None
        return _acknowledgement(outcome)


def _acknowledgement(outcome: ApprovalReplyOutcome) -> str:
    """Name the action when the reply decided exactly one, so the user hears what it settled."""
    approved = outcome.action == "approve"
    if len(outcome.decided) != 1:
        return HIL_ACK_APPROVED if approved else HIL_ACK_DENIED
    [record] = outcome.decided
    action = describe_call(record.tool_name, record.args, None).action
    template = HIL_ACK_APPROVED_ONE if approved else HIL_ACK_DENIED_ONE
    return template.format(action=action[:1].lower() + action[1:])
