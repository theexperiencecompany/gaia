"""Per-message feedback endpoint — wires the chat UI's thumbs to Langfuse scores.

trace_id is deterministically derived from the assistant `message_id`, so the
score lands on the exact reply without persisting any extra state. The
existing PostHog event continues to fire on the frontend side; this endpoint
is additive.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from langfuse import get_client
from pydantic import BaseModel, Field

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.langfuse import trace_id_for_message
from app.db.mongodb.collections import conversations_collection
from shared.py.wide_events import log

router = APIRouter()

SCORE_NAME = "user_feedback"


class MessageFeedbackRequest(BaseModel):
    is_positive: bool = Field(description="True for thumbs-up, False for thumbs-down.")


@router.post(
    "/messages/{message_id}/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit thumbs-up / thumbs-down feedback for a message",
)
async def submit_message_feedback(
    message_id: str,
    payload: MessageFeedbackRequest,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    user_id = user["user_id"]
    value = 1 if payload.is_positive else -1
    log.set(
        user={"id": user_id},
        feedback={"message_id": message_id, "is_positive": payload.is_positive},
    )

    # Confirm the caller owns the conversation this message belongs to.
    conversation = await conversations_collection.find_one(
        {"user_id": user_id, "messages.message_id": message_id},
        {"conversation_id": 1},
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Message not found")

    trace_id = trace_id_for_message(message_id)
    if trace_id is None:
        # Langfuse isn't configured in this env — PostHog has already
        # captured the click on the frontend, so we ack without scoring.
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "ok", "scored": False, "reason": "langfuse_disabled"},
        )

    get_client().create_score(
        trace_id=trace_id,
        name=SCORE_NAME,
        value=value,
        data_type="NUMERIC",
        metadata={
            "message_id": message_id,
            "conversation_id": conversation.get("conversation_id"),
            "user_id": user_id,
            "source": "chat_ui_thumbs",
        },
    )
    log.set(feedback={"langfuse": "scored", "trace_id": trace_id})

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "ok", "scored": True, "trace_id": trace_id},
    )
