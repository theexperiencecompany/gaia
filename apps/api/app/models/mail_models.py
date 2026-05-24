import base64
from enum import Enum
import json

from pydantic import BaseModel, Field, model_validator


class EmailRequest(BaseModel):
    prompt: str
    subject: str | None = None
    body: str | None = None
    writingStyle: str | None = None
    contentLength: str | None = None
    clarityOption: str | None = None


class EmailSummaryRequest(BaseModel):
    message_id: str
    include_action_items: bool | None = None
    max_length: int | None = None


class SendEmailRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None


class EmailReadStatusRequest(BaseModel):
    message_ids: list[str]


class EmailActionRequest(BaseModel):
    """Request model for performing actions on emails like star, trash, archive."""

    message_ids: list[str]


class LabelRequest(BaseModel):
    """Request model for creating or updating Gmail labels."""

    name: str
    label_list_visibility: str | None = Field(
        default="labelShow",
        description="Whether the label appears in the label list: 'labelShow', 'labelHide', 'labelShowIfUnread'",
    )
    message_list_visibility: str | None = Field(
        default="show",
        description="Whether the label appears in the message list: 'show', 'hide'",
    )
    background_color: str | None = None
    text_color: str | None = None


class ApplyLabelRequest(BaseModel):
    """Request model for applying or removing labels from messages."""

    message_ids: list[str]
    label_ids: list[str]


class DraftRequest(BaseModel):
    """Request model for creating or updating a draft email.

    ``body`` may be Markdown or HTML — the Composio Gmail hook converts
    Markdown to HTML before sending, so callers never need to choose.
    """

    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None


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
    emailAddress: str | None = None
    historyId: int | None = None

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
            raise ValueError(f"Failed to decode message data: {e!s}")

        return values


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
    def list(cls) -> list[str]:
        """Return a list of all importance levels."""
        return [level.value for level in cls]


class EmailComprehensiveAnalysis(BaseModel):
    """Combined response model for email importance and semantic analysis."""

    # Importance analysis fields
    is_important: bool = Field(description="Whether the email is important and requires attention")
    importance_level: EmailImportanceLevelEnum = Field(
        description="Importance level: URGENT, HIGH, MEDIUM, or LOW"
    )
    summary: str = Field(
        description="Brief summary of the email if important, empty string if not important"
    )

    # Semantic labeling fields
    semantic_labels: list[str] = Field(
        description="List of semantic labels that categorize the email content and context"
    )
