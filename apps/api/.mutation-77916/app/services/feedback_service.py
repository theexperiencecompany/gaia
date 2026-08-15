"""Business logic for per-message chat feedback."""

from langfuse import get_client

from app.config.langfuse import trace_id_for_message
from app.db.repositories.conversations import conversation_repository
from app.models.feedback_models import MessageFeedbackResponse
from app.utils.errors import AppError

SCORE_NAME = "user_feedback"


async def create_message_feedback_service(
    *,
    user_id: str,
    message_id: str,
    is_positive: bool,
) -> MessageFeedbackResponse:
    """Record thumbs-up/down on a message the caller owns."""
    conversation_id = await conversation_repository.find_owner_of_message(user_id, message_id)
    if conversation_id is None:
        raise AppError(message="Message not found", status_code=404)

    trace_id = trace_id_for_message(message_id)
    if trace_id is None:
        return MessageFeedbackResponse(scored=False, reason="langfuse_disabled")

    value = 1 if is_positive else -1
    get_client().create_score(
        trace_id=trace_id,
        name=SCORE_NAME,
        value=value,
        data_type="NUMERIC",
        metadata={
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "source": "chat_ui_thumbs",
        },
    )
    return MessageFeedbackResponse(scored=True, trace_id=trace_id)
