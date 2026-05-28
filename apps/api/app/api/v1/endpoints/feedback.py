"""Per-message feedback endpoint.

Trace IDs derive deterministically from `message_id`, so scores attach to
the matching trace without ever persisting the ID.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.feedback_models import MessageFeedbackRequest, MessageFeedbackResponse
from app.services.feedback_service import create_message_feedback_service
from shared.py.wide_events import log

router = APIRouter()


@router.post(
    "/messages/{message_id}/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit thumbs-up / thumbs-down feedback for a message",
)
async def submit_message_feedback(
    message_id: str,
    payload: MessageFeedbackRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> MessageFeedbackResponse:
    """Record a thumbs-up/down on an assistant reply owned by the caller."""
    user_id = user["user_id"]
    log.set(
        user={"id": user_id},
        feedback={"message_id": message_id, "is_positive": payload.is_positive},
    )

    result = await create_message_feedback_service(
        user_id=user_id,
        message_id=message_id,
        is_positive=payload.is_positive,
    )

    log.set(feedback={"scored": result.scored, "trace_id": result.trace_id})
    return result
