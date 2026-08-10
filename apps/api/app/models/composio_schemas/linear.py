"""
Linear trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/linear.ts
"""

from pydantic import BaseModel, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


class LinearIssueCreatedPayload(BaseModel):  # type: ignore[explicit-any]
    """Payload for LINEAR_ISSUE_CREATED_TRIGGER."""

    action: str | None = Field(None, description="Action (create)")
    data: dict[str, object] | None = Field(None, description="Issue data")
    type: str | None = Field(None, description="Issue type")
    url: str | None = Field(None, description="Issue URL")


class LinearCommentAddedPayload(BaseModel):  # type: ignore[explicit-any]
    """Payload for LINEAR_COMMENT_EVENT_TRIGGER."""

    action: str | None = Field(None, description="Action (create)")
    data: dict[str, object] | None = Field(None, description="Comment data")
    type: str | None = Field(None, description="Type")
    url: str | None = Field(None, description="Comment URL")
