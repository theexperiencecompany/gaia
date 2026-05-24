"""
Workflow Execution Models.

Models for tracking workflow execution history.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowExecution(BaseModel):
    """A single workflow execution record."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="ID of the workflow that was executed")
    user_id: str = Field(description="ID of the user who owns the workflow")
    status: Literal["running", "success", "failed"] = Field(
        default="running", description="Current status of the execution"
    )
    started_at: datetime = Field(description="When the execution started")
    completed_at: datetime | None = Field(default=None, description="When the execution completed")
    duration_seconds: float | None = Field(
        default=None, description="Execution duration in seconds"
    )
    conversation_id: str | None = Field(
        default=None, description="Conversation containing the full execution"
    )
    summary: str | None = Field(
        default=None, description="Brief summary of what the execution accomplished"
    )
    error_message: str | None = Field(default=None, description="Error message if execution failed")
    trigger_type: str = Field(
        default="manual",
        description="What triggered the execution: manual, schedule, or integration name",
    )


class WorkflowExecutionsResponse(BaseModel):
    """Response for workflow executions list endpoint."""

    executions: list[WorkflowExecution] = Field(
        default_factory=list, description="List of workflow executions"
    )
    total: int = Field(default=0, description="Total number of executions")
    has_more: bool = Field(default=False, description="Whether there are more executions to load")
