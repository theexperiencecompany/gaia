"""
Todoist trigger payload models.

Field set verified against the Composio triggers_types API (2026-08).
"""

from typing import Any

from pydantic import BaseModel, Field


class TodoistNewTaskCreatedPayload(BaseModel):
    """Payload for TODOIST_NEW_TASK_CREATED."""

    event_type: str | None = Field(None, description="Type of event")
    task: dict[str, Any] | None = Field(None, description="The Todoist task object")
