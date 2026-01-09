"""
Linear trigger payload models.

Reference: node_modules/@composio/core/generated/linear.ts
"""

from typing import Any

from pydantic import BaseModel, Field


class LinearIssueCreatedPayload(BaseModel):
    """Payload for LINEAR_ISSUE_CREATED_TRIGGER."""

    action: str | None = Field(None, description="Action (create)")
    data: dict[str, Any] | None = Field(None, description="Issue data")
    type: str | None = Field(None, description="Issue type")
    url: str | None = Field(None, description="Issue URL")


class LinearCommentAddedPayload(BaseModel):
    """Payload for LINEAR_COMMENT_EVENT_TRIGGER."""

    action: str | None = Field(None, description="Action (create)")
    data: dict[str, Any] | None = Field(None, description="Comment data")
    type: str | None = Field(None, description="Type")
    url: str | None = Field(None, description="Comment URL")
