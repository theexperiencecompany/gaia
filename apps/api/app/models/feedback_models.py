"""Pydantic models for per-message chat feedback (thumbs up / thumbs down)."""

from pydantic import BaseModel, Field


class MessageFeedbackRequest(BaseModel):  # type: ignore[explicit-any]
    is_positive: bool = Field(description="True for thumbs-up, False for thumbs-down.")


class MessageFeedbackResponse(BaseModel):  # type: ignore[explicit-any]
    """`scored=False` with `reason="langfuse_disabled"` is a successful ack."""

    status: str = "ok"
    scored: bool
    trace_id: str | None = None
    reason: str | None = None
