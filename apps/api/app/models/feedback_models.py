"""Pydantic models for per-message chat feedback (thumbs up / thumbs down)."""

from pydantic import BaseModel, Field


class MessageFeedbackRequest(BaseModel):
    """Body of POST /messages/{message_id}/feedback."""

    is_positive: bool = Field(description="True for thumbs-up, False for thumbs-down.")


class MessageFeedbackResponse(BaseModel):
    """Outcome of a feedback submission.

    `scored=False` with `reason="langfuse_disabled"` is a successful ack
    when the environment has no Langfuse configured — PostHog has already
    captured the click on the frontend.
    """

    status: str = "ok"
    scored: bool
    trace_id: str | None = None
    reason: str | None = None
