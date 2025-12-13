import base64
import json
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field, model_validator


class EmailProcessingResult(BaseModel):
    """Result of processing a single email."""

    message_id: str = Field(description="Gmail message ID")
    success: bool = Field(description="Whether processing succeeded")
    memory_id: Optional[str] = Field(
        default=None, description="Mem0 memory ID if successful"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")


class EmailBatchResult(BaseModel):
    """Result of processing a batch of emails."""

    total_emails: int = Field(description="Total emails processed")
    successful_count: int = Field(description="Number of successful memories created")
    failed_count: int = Field(description="Number of failed email processings")
    memory_ids: List[str] = Field(
        default_factory=list, description="List of created memory IDs"
    )
    errors: List[str] = Field(
        default_factory=list, description="List of errors encountered"
    )


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


class EmailSearchRequest(BaseModel):
    """Request model for advanced email search functionality."""

    query: Optional[str] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    has_attachment: Optional[bool] = None
    attachment_type: Optional[str] = None
    date_from: Optional[Union[datetime, str]] = None
    date_to: Optional[Union[datetime, str]] = None
    labels: Optional[List[str]] = None
    is_read: Optional[bool] = None
    max_results: Optional[int] = Field(default=20, ge=1, le=100)
    page_token: Optional[str] = None


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


class EmailWebhookMessage(BaseModel):
    """
    Model for the message part of the webhook request.
    The `data` field is a base64 encoded JSON string containing `emailAddress` and `historyId`.
    """

    messageId: str
    publishTime: str
    data: str = Field(
        ...,
        description="Base64 encoded string of the email data. Contains emailAddress and historyId.",
    )

    # Decoded fields extracted from data
    emailAddress: Optional[str] = None
    historyId: Optional[int] = None

    @model_validator(mode="before")
    def decode_data(cls, values):
        try:
            encoded = values.get("data")
            decoded_bytes = base64.urlsafe_b64decode(encoded + "==")
            decoded_str = decoded_bytes.decode("utf-8")
            decoded_json = json.loads(decoded_str)

            values["emailAddress"] = decoded_json.get("emailAddress")
            values["historyId"] = decoded_json.get("historyId")
        except Exception as e:
            raise ValueError(f"Failed to decode message data: {str(e)}")

        return values


class EmailWebhookRequest(BaseModel):
    """Request model for handling email webhooks."""

    message: EmailWebhookMessage
    subscription: str


class EmailWorkflowFilterDecision(BaseModel):
    """Model for LLM decision on whether to process an email for a specific workflow"""

    should_process: bool = Field(
        description="Boolean decision: true if this email should trigger the workflow, false if it should be skipped"
    )
    reasoning: str = Field(
        description="Brief explanation of why this email should or should not trigger the workflow"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence level in the decision (0.0 to 1.0)",
    )


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


class EmailComprehensiveAnalysis(BaseModel):
    """Combined response model for email importance and semantic analysis."""

    # Importance analysis fields
    is_important: bool = Field(
        description="Whether the email is important and requires attention"
    )
    importance_level: EmailImportanceLevelEnum = Field(
        description="Importance level: URGENT, HIGH, MEDIUM, or LOW"
    )
    summary: str = Field(
        description="Brief summary of the email if important, empty string if not important"
    )

    # Semantic labeling fields
    semantic_labels: List[str] = Field(
        description="List of semantic labels that categorize the email content and context"
    )


class EmailComposeRequest(BaseModel):
    """Model for email composition requests."""

    body: str = Field(
        ...,
        min_length=0,
        max_length=10000,
        description="Body content of the email",
    )
    subject: str = Field(
        ...,
        min_length=0,
        max_length=200,
        description="Subject line for the email",
    )
    to: List[str] = Field(
        ...,
        description="List of recipient email addresses",
    )
    draft_id: Optional[str] = Field(
        None,
        description="ID of the created draft email",
    )
    thread_id: Optional[str] = Field(
        None,
        description="ID of the email thread this reply belongs to",
    )

    @model_validator(mode="after")
    def validate_emails(self) -> "EmailComposeRequest":
        """Validate that all email addresses are valid."""
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        for email in self.to:
            if not re.match(email_pattern, email.strip()):
                raise ValueError(f"Invalid email address: {email}")

        return self
