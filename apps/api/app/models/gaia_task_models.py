"""
GaiaTask models — GAIA's internal working memory for multi-step tasks.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class GaiaTaskStatus(str, Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    STALLED = "stalled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ESCALATING = "escalating"


class GaiaTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    title: str
    description: str
    status: GaiaTaskStatus = GaiaTaskStatus.ACTIVE
    primary_conversation_id: str | None = None
    owned_workflow_ids: list[str] = Field(default_factory=list)
    active_loop_ids: list[str] = Field(default_factory=list)
    vfs_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    expires_at: datetime | None = None


class CreateGaiaTaskRequest(BaseModel):
    title: str
    description: str
    expires_in_days: int | None = 30
    primary_conversation_id: str | None = None


class UpdateGaiaTaskRequest(BaseModel):
    status: GaiaTaskStatus | None = None
    notes: str | None = None  # Appended to log.md
    active_loop_ids: list[str] | None = None
    owned_workflow_ids: list[str] | None = None
