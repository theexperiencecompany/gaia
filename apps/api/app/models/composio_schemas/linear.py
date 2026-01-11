"""
Linear trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/linear.ts
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


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


# =============================================================================
# Tool Output Schemas
# =============================================================================


class LinearIssueState(BaseModel):
    """Linear issue state."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    color: str | None = None


class LinearIssue(BaseModel):
    """Single Linear issue from LINEAR_LIST_LINEAR_ISSUES."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    description: str | None = None
    state: LinearIssueState | None = None
    priority: int | None = None
    url: str | None = None


class LinearListIssuesData(BaseModel):
    """Output data for LINEAR_LIST_LINEAR_ISSUES tool."""

    model_config = ConfigDict(extra="ignore")

    issues: list[LinearIssue] = Field(default_factory=list)
    page_info: dict[str, Any] = Field(default_factory=dict)
