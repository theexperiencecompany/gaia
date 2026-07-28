from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class EmailRequest(BaseModel):
    prompt: str
    subject: str | None = None
    body: str | None = None
    writingStyle: str | None = None
    contentLength: str | None = None
    clarityOption: str | None = None


class ComposedEmailOutput(BaseModel):
    """Structured output of the AI email composer."""

    subject: str = Field(description="Generated email subject line")
    body: str = Field(description="Generated email body")


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


class MailDocument(UserScopedDocument):
    """An analyzed-email importance summary as stored in the mail collection.

    ``extra="allow"`` because the analyzer stores a variable set of summary fields
    that the read endpoints return verbatim; keeping them avoids dropping data.
    """

    model_config = ConfigDict(extra="allow")

    message_id: str
    is_important: bool = False
    analyzed_at: datetime | None = None


class MailUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_important: bool | None = None


class EmailImportanceSummariesResponse(BaseModel):
    """Response for ``GET /gmail/importance-summaries``.

    ``emails`` entries stay ``dict[str, Any]`` because they are JSON dumps of
    ``MailDocument``, which allows analyzer-supplied extra fields that vary per email.
    """

    status: Literal["success"]
    emails: list[dict[str, Any]]
    count: int
    filtered_by_importance: bool


class EmailImportanceSummaryResponse(BaseModel):
    """Response for ``GET /gmail/importance-summary/{message_id}``.

    ``email`` stays ``dict[str, Any]`` for the same reason as
    ``EmailImportanceSummariesResponse.emails``.
    """

    status: Literal["success"]
    email: dict[str, Any]


class BulkEmailImportanceSummariesResponse(BaseModel):
    """Response for ``POST /gmail/importance-summaries/bulk``.

    ``emails`` values stay ``dict[str, Any]`` for the same reason as
    ``EmailImportanceSummariesResponse.emails``.
    """

    status: Literal["success"]
    emails: dict[str, dict[str, Any]]
    found_count: int
    missing_count: int
    found_message_ids: list[str]
    missing_message_ids: list[str]
