"""
GaiaTask models for the persistent task registry.

GaiaTasks bridge chat sessions and background workflows, allowing
multi-step interactions (meeting scheduling, email follow-ups) to
persist across sessions with their own conversation and VFS folder.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GaiaTaskStatus(str, Enum):
    ACTIVE = "active"
    WAITING_FOR_REPLY = "waiting_for_reply"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GaiaTaskCategory(str, Enum):
    MEETING_SCHEDULING = "meeting_scheduling"
    EMAIL_FOLLOW_UP = "email_follow_up"
    INBOX_MANAGEMENT = "inbox_management"
    EMAIL_THREAD_TRACKING = "email_thread_tracking"
    GENERAL = "general"


class GaiaTask(BaseModel):
    id: Optional[str] = None
    user_id: str
    title: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    category: GaiaTaskCategory
    status: GaiaTaskStatus

    # Session architecture
    task_conversation_id: str
    created_from_conversation_id: str

    # VFS folder path
    vfs_folder: str

    # Trigger matching
    watched_thread_ids: list[str] = Field(default_factory=list)
    watched_senders: list[str] = Field(default_factory=list)

    # LLM-facing context
    waiting_for: Optional[str] = Field(default=None, max_length=300)
    last_update: Optional[str] = Field(default=None, max_length=500)

    # Lifecycle
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None


class GaiaTaskCreate(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    category: GaiaTaskCategory = GaiaTaskCategory.GENERAL
    created_from_conversation_id: str
    watched_thread_ids: list[str] = Field(default_factory=list)
    watched_senders: list[str] = Field(default_factory=list)
    waiting_for: Optional[str] = Field(default=None, max_length=300)
    expires_in_days: Optional[int] = 14


class GaiaTaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[GaiaTaskStatus] = None
    waiting_for: Optional[str] = Field(default=None, max_length=300)
    last_update: Optional[str] = Field(default=None, max_length=500)
    watched_thread_ids: Optional[list[str]] = None
    watched_senders: Optional[list[str]] = None
