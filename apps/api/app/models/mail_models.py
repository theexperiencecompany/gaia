from typing import Any, TypedDict

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ResponseModel


class GmailSearchFilters(BaseModel):
    """Advanced-search filters for the Gmail search endpoint."""

    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None
    has_attachment: bool | None = None
    attachment_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    label: str | None = None
    is_read: bool | None = None


class SendEmailForm(BaseModel):
    """Multipart-form fields for the Gmail send endpoint."""

    to: str
    subject: str
    body: str
    thread_id: str | None = None
    cc: str | None = None
    bcc: str | None = None
    attachments: list[UploadFile] | None = None


# Gmail message payloads below stay dict[str, Any]: Google owns that schema, and
# transform_gmail_message spreads the raw Composio message before adding derived
# keys, so the field set varies. Only API-built envelopes are modelled.


class GmailToolResult(BaseModel):
    """The result of one Composio Gmail tool invocation.

    Composio's own envelope is exactly ``{data, error, successful}``
    (``composio.core.models.tools.ToolExecutionResponse``). ``id``/``thread_id``
    are the root-level keys GMAIL_SEND_DRAFT returns; ``extra="allow"`` keeps
    everything else the provider sends.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    successful: bool = True
    error: str | None = None
    data: dict[str, Any] | None = None
    id: str | None = None
    thread_id: str | None = Field(default=None, alias="threadId")


class GmailFetchEmailsData(BaseModel):
    """The ``data`` payload of a ``GMAIL_FETCH_EMAILS`` result."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    messages: list[dict[str, Any]] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")

    @field_validator("next_page_token")
    @classmethod
    def _last_page_has_no_token(cls, token: str | None) -> str | None:
        """Composio marks the last page with "", which the API contract spells None."""
        return token or None


class GmailMessageSummary(ResponseModel):
    """One message as ``transform_gmail_message`` shapes it for the web client.

    The declared fields are the derived ones every consumer reads; the raw
    Gmail/Composio keys ride along via ``extra="allow"`` exactly as before.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    thread_id: str = Field(default="", alias="threadId")
    sender: str = Field(default="", alias="from")
    to: str = ""
    cc: str = ""
    reply_to: str = Field(default="", alias="replyTo")
    subject: str = ""
    time: str = ""
    snippet: str = ""
    body: str = ""
    is_thread: bool = Field(default=False, alias="isThread")
    is_unread: bool = False
    label_ids: list[str] = Field(default_factory=list, alias="labelIds")


class GmailMessagesResponse(BaseModel):
    """Response for ``GET /gmail/search``: the ``search_messages`` result, forwarded unchanged."""

    messages: list[GmailMessageSummary]
    next_page_token: str | None = Field(default=None, serialization_alias="nextPageToken")

    def raw_messages(self) -> list[dict[str, object]]:
        """The messages as the dicts ``transform_gmail_message`` produced.

        The memory pipeline (``email_processor``, ``process_email_content``) still
        reads Gmail messages by key; this is its one conversion point.
        """
        return [message.model_dump(by_alias=True) for message in self.messages]


class SendEmailWithAttachmentsResponse(BaseModel):
    """Response for ``POST /gmail/send``, which also reports the attachment count."""

    message_id: str | None
    status: str
    attachments_count: int


class SendDraftResponse(BaseModel):
    """Response for ``POST /gmail/drafts/{draft_id}/send``."""

    message_id: str
    thread_id: str
    status: str
    successful: bool


class AttachmentReference(BaseModel):
    """One file to attach, referenced by exactly one source."""

    workspace_path: str | None = Field(
        default=None,
        description="Path to a file in the current session workspace (relative to /workspace).",
    )
    url: str | None = Field(
        default=None,
        description="A fetchable URL to the file, e.g. a Google Drive download link.",
    )
    name: str | None = Field(
        default=None, description="Optional filename to use for the attachment."
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "AttachmentReference":
        if bool(self.workspace_path) == bool(self.url):
            raise ValueError("need exactly one of workspace_path or url")  # pragma: no mutate
        return self


class ComposioAttachment(TypedDict):
    """The ``FileUploadable`` shape Composio's compose tools expect."""

    name: str
    mimetype: str
    s3key: str


def attachment_references_param_schema(description: str) -> dict[str, object]:
    """Agent-facing schema for the friendly ``attachments`` array param.

    Item properties are derived from ``AttachmentReference`` field descriptions,
    so a field change lands in one place instead of drifting between the model
    and a hand-written schema dict. Kept ``{"type": "string"}`` (not the model's
    nullable anyOf) to match the shape agents already see.
    """
    return {
        "type": "array",
        "description": description,
        "items": {
            "type": "object",
            "properties": {
                name: {"type": "string", "description": field.description}
                for name, field in AttachmentReference.model_fields.items()
            },
        },
    }
