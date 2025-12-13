"""Support request models for the GAIA API."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class SupportRequestType(str, Enum):
    """Types of support requests."""

    SUPPORT = "support"
    FEATURE = "feature"


class SupportRequestStatus(str, Enum):
    """Status of support requests."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportRequestPriority(str, Enum):
    """Priority levels for support requests."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SupportAttachment(BaseModel):
    """Model for support request attachments."""

    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="MIME type of the file")
    file_url: Optional[str] = Field(None, description="URL to access the file")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Upload timestamp",
    )


class SupportRequestCreate(BaseModel):
    """Request model for creating a support request."""

    type: SupportRequestType = Field(
        ..., description="Type of request (support or feature)"
    )
    title: str = Field(
        ..., min_length=1, max_length=200, description="Title of the request"
    )
    description: str = Field(
        ..., min_length=10, max_length=5000, description="Detailed description"
    )


class SupportRequestResponse(BaseModel):
    """Response model for support requests."""

    id: str = Field(..., description="Unique identifier for the support request")
    ticket_id: str = Field(..., description="Human-readable ticket ID")
    user_id: str = Field(..., description="ID of the user who created the request")
    user_email: str = Field(
        ..., description="Email of the user who created the request"
    )
    user_name: Optional[str] = Field(
        None, description="Name of the user who created the request"
    )
    type: SupportRequestType = Field(..., description="Type of request")
    title: str = Field(..., description="Title of the request")
    description: str = Field(..., description="Description of the request")
    status: SupportRequestStatus = Field(
        default=SupportRequestStatus.OPEN, description="Current status"
    )
    priority: SupportRequestPriority = Field(
        default=SupportRequestPriority.MEDIUM, description="Priority level"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    resolved_at: Optional[datetime] = Field(None, description="Resolution timestamp")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    attachments: List[SupportAttachment] = Field(
        default_factory=list, description="File attachments"
    )


class SupportRequestUpdate(BaseModel):
    """Request model for updating a support request."""

    status: Optional[SupportRequestStatus] = Field(None, description="New status")
    priority: Optional[SupportRequestPriority] = Field(None, description="New priority")
    tags: Optional[List[str]] = Field(None, description="New tags")
    notes: Optional[str] = Field(None, description="Internal notes")


class SupportRequestSubmissionResponse(BaseModel):
    """Response model for support request submission."""

    success: bool = Field(..., description="Whether the submission was successful")
    message: str = Field(..., description="Response message")
    ticket_id: Optional[str] = Field(None, description="Generated ticket ID")
    support_request: Optional[SupportRequestResponse] = Field(
        None, description="Created support request details"
    )


class SupportEmailNotification(BaseModel):
    """Model for email notification data."""

    user_name: str
    user_email: str
    ticket_id: str
    type: SupportRequestType
    title: str
    description: str
    created_at: datetime
    support_emails: List[EmailStr]
    attachments: List[SupportAttachment] = []
