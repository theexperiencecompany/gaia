"""The ApprovalReplies port over the HIL reply classifier, for button-less surfaces."""

from app.constants.hil import ApprovalDecision
from app.constants.log_tags import LogTag
from app.services.hil.conversational import resolve_pending_from_message
from shared.py.wide_events import log


class HilApprovalReplies:
    """Classifies a typed reply against the conversation's pending approvals and resolves them."""

    async def classify(
        self, conversation_id: str, user_id: str, message_text: str
    ) -> ApprovalDecision | None:
        """Return approve or deny; None when the reply is unrelated, nothing was pending, or classifying failed."""
        try:
            action = await resolve_pending_from_message(conversation_id, user_id, message_text)
        except Exception as error:  # an unread reply is answered by a normal comms run instead
            log.error(
                f"{LogTag.HIL} approval reply classification failed",
                error=str(error),
                error_type=type(error).__name__,
                conversation_id=conversation_id,
            )
            return None
        if action == "approve" or action == "deny":
            return action
        return None
