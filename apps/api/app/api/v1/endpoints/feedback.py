"""Per-message feedback endpoint.

Surfaces the thumbs-up / thumbs-down clicks from the chat UI as Langfuse
scores. The trace_id is deterministically derived from the assistant
`message_id` (see `trace_id_for_message` in `app/config/langfuse.py`),
so the score lands on the exact reply without persisting any extra
state to MongoDB.

The existing PostHog event continues to fire on the frontend side; this
endpoint is additive.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.langfuse import _langfuse_configured, trace_id_for_message
from app.db.mongodb.collections import conversations_collection
from shared.py.wide_events import log

router = APIRouter()

SCORE_NAME = "user_feedback"


class MessageFeedbackRequest(BaseModel):
    """User feedback for a specific assistant message."""

    is_positive: bool = Field(description="True for thumbs-up, False for thumbs-down.")
    comment: str | None = Field(default=None, max_length=2000)


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
    value: Literal[1, -1] = 1 if payload.is_positive else -1
    log.set(
        user={"id": user_id},
        feedback={
            "message_id": message_id,
            "is_positive": payload.is_positive,
        },
    )

    # Verify the message belongs to a conversation owned by the caller.
    # Conversations embed messages; we only need to confirm ownership,
    # not load the entire conversation document.
    conversation = await conversations_collection.find_one(
        {
            "user_id": user_id,
            "messages.message_id": message_id,
        },
        {"conversation_id": 1, "messages.message_id": 1, "messages.type": 1},
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Message not found")

    if not _langfuse_configured():
        # Langfuse is opt-in; if it isn't configured for this env we still
        # acknowledge the click — PostHog has already captured it on the
        # frontend — and we don't fail loudly.
        log.set(feedback={"langfuse": "not_configured"})
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "ok", "scored": False, "reason": "langfuse_disabled"},
        )

    trace_id = trace_id_for_message(message_id)
    if trace_id is None:
        # Should not happen given the configured check above, but stay defensive.
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "ok", "scored": False, "reason": "no_trace_id"},
        )

    # Defer the langfuse import so missing/optional installs never break
    # the rest of this module.
    from langfuse import get_client  # noqa: PLC0415

    client = get_client()
    client.create_score(
        trace_id=trace_id,
        name=SCORE_NAME,
        value=value,
        data_type="NUMERIC",
        comment=payload.comment,
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
