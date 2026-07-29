"""
Workflow Execution Models.

Models for tracking workflow execution history.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument

# The run-states an execution record may hold: created as ``running``, then
# exactly one terminal write. Named once here because the document, the update
# model, the repository's ``complete`` and the service's ``complete_execution``
# all speak it (Type Safety items 3 and 5).
WorkflowExecutionStatus = Literal["running", "success", "failed"]


class WorkflowExecution(BaseModel):
    """A single workflow execution record."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="ID of the workflow that was executed")
    user_id: str = Field(description="ID of the user who owns the workflow")
    status: WorkflowExecutionStatus = Field(
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


class WorkflowExecutionDocument(WorkflowExecution, MongoDocument):
    """A workflow execution as stored in MongoDB.

    Identity is the business key ``execution_id``; Mongo's ``_id`` is an
    incidental ObjectId and the inherited ``id`` is unused. Being a subclass of
    ``WorkflowExecution`` it doubles as the API/read model directly.
    """


class WorkflowExecutionUpdate(BaseModel):
    """Partial ``$set`` update for an execution — the completion fields."""

    model_config = ConfigDict(extra="forbid")

    status: WorkflowExecutionStatus | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    error_message: str | None = None
    conversation_id: str | None = None
