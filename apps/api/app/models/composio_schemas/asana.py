"""
Asana trigger payload models.

Field sets verified against the Composio triggers_types API (2026-08);
the legacy ASANA_TASK_TRIGGER slug is retired upstream in favor of
ASANA_TASK_CREATED.
"""

from pydantic import BaseModel, Field


class AsanaTaskCreatedPayload(BaseModel):
    """Payload for ASANA_TASK_CREATED."""

    created_at: str | None = Field(None, description="Timestamp of the event")
    project_gid: str | None = Field(None, description="GID of the project the task was added to")
    task_gid: str | None = Field(None, description="GID of the created task")
    user_gid: str | None = Field(None, description="GID of the user who created the task")
