"""
GaiaTask models — GAIA's internal working memory for multi-step tasks.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

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
    primary_conversation_id: Optional[str] = None
    owned_workflow_ids: List[str] = Field(default_factory=list)
    active_loop_ids: List[str] = Field(default_factory=list)
    vfs_path: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class CreateGaiaTaskRequest(BaseModel):
    title: str
    description: str
    expires_in_days: Optional[int] = 30
    primary_conversation_id: Optional[str] = None


class UpdateGaiaTaskRequest(BaseModel):
    status: Optional[GaiaTaskStatus] = None
    notes: Optional[str] = None  # Appended to log.md
    active_loop_ids: Optional[List[str]] = None
    owned_workflow_ids: Optional[List[str]] = None


class GaiaTaskSummary(BaseModel):
    """Lightweight representation injected into every agent call."""

    task_id: str
    title: str
    status: GaiaTaskStatus
    created_at: datetime
    active_loop_count: int
