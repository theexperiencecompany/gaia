"""The ApprovalReplies port over the HIL reply classifier, for button-less surfaces."""

from app.constants.hil import ApprovalDecision
from app.models.message_models import MessageDict
from app.services.hil.conversational import (
    classifier_history,
    resolve_pending_from_message,
)


class HilApprovalReplies:
    """Resolves a typed reply against the conversation's pending approvals, each with its own decision."""

    async def resolve(
        self, conversation_id: str, user_id: str, message_text: str, history: list[MessageDict]
    ) -> ApprovalDecision | None:
        """Return approve when anything was approved, deny when only declined; None when the reply decided nothing.

        Each decided approval logs its own ApprovalDecided as the HIL resolution records it. A
        failure propagates: a retry re-reads what is still pending, so nothing is decided twice.
        """
        action = await resolve_pending_from_message(
            conversation_id, user_id, message_text, classifier_history(history)
        )
        if action == "approve" or action == "deny":
            return action
        return None
