from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EmailRequest(BaseModel):
    prompt: str
    subject: Optional[str] = None
    body: Optional[str] = None
    writingStyle: Optional[str] = None
    contentLength: Optional[str] = None
    clarityOption: Optional[str] = None


class EmailSummaryRequest(BaseModel):
    message_id: str
    include_action_items: Optional[bool] = None
    max_length: Optional[int] = None


class SendEmailRequest(BaseModel):
    to: List[str]
    subject: str
    body: str
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None


class EmailReadStatusRequest(BaseModel):
    message_ids: List[str]


class EmailActionRequest(BaseModel):
    """Request model for performing actions on emails like star, trash, archive."""

    message_ids: List[str]


class LabelRequest(BaseModel):
    """Request model for creating or updating Gmail labels."""

    name: str
    label_list_visibility: Optional[str] = Field(
        default="labelShow",
        description="Whether the label appears in the label list: 'labelShow', 'labelHide', 'labelShowIfUnread'",
    )
    message_list_visibility: Optional[str] = Field(
        default="show",
        description="Whether the label appears in the message list: 'show', 'hide'",
    )
    background_color: Optional[str] = None
    text_color: Optional[str] = None


class ApplyLabelRequest(BaseModel):
    """Request model for applying or removing labels from messages."""

    message_ids: List[str]
    label_ids: List[str]


class DraftRequest(BaseModel):
    """Request model for creating or updating a draft email."""

    to: List[str]
    subject: str
    body: str
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    is_html: Optional[bool] = False


class EmailImportanceLevelEnum(str, Enum):
    """Enumeration for email importance levels."""

    URGENT = "URGENT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @classmethod
    def list(cls) -> List[str]:
        """Return a list of all importance levels."""
        return [level.value for level in cls]
