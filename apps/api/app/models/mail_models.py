from datetime import datetime
from typing import Any, Literal, TypedDict

from fastapi import UploadFile
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


class SendEmailRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None


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


# Every Gmail message, label and draft payload below stays ``dict[str, Any]``:
# Google owns those schemas and ``transform_gmail_message`` spreads the raw
# Composio message before adding its derived keys, so the field set varies per
# message. Only the envelopes the API builds itself are modelled here.


class GmailAttachmentPayload(TypedDict):
    """One entry of the ``attachments`` parameter Composio's Gmail compose tools take."""

    filename: str | None
    content: bytes
    content_type: str | None


class GmailToolResult(BaseModel):
    """The result of one Composio Gmail tool invocation.

    Composio's own envelope is exactly ``{data, error, successful}``
    (``composio.core.models.tools.ToolExecutionResponse``). The fields after it
    are the *root-level* keys ``mail_service`` reads off individual Gmail tools —
    all optional, since no single tool sets more than one of them. ``extra="allow"``
    keeps everything else the provider sends, so ``as_payload()`` reproduces the
    original response for the routes that forward it verbatim.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    successful: bool = True
    error: str | None = None
    data: dict[str, Any] | None = None
    messages: list[dict[str, Any]] | None = None
    labels: list[dict[str, Any]] | None = None
    drafts: list[dict[str, Any]] | None = None
    message: dict[str, Any] | None = None
    id: str | None = None
    thread_id: str | None = Field(default=None, alias="threadId")
    next_page_token: str | None = Field(default=None, alias="nextPageToken")

    def as_payload(self) -> dict[str, Any]:
        """The response exactly as the provider sent it — keys it omitted stay omitted."""
        return self.model_dump(exclude_unset=True, by_alias=True)


class GmailFetchEmailsData(BaseModel):
    """The ``data`` payload of a ``GMAIL_FETCH_EMAILS`` result."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    messages: list[dict[str, Any]] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class GmailMessageResource(BaseModel):
    """A Gmail ``messages`` resource returned by the label-modification tools.

    Only ``id`` is declared — it is the one field every caller reads, and Gmail
    always sends it; the rest of the payload rides along via ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    id: str


class GmailMessagesResponse(BaseModel):
    """Response for ``GET /gmail/messages`` and ``GET /gmail/search``, and the return
    shape of ``search_messages``, which the routes forward unchanged."""

    messages: list[dict[str, Any]]
    next_page_token: str | None = Field(default=None, serialization_alias="nextPageToken")


class GmailLabelsResult(BaseModel):
    """Return shape of ``list_labels`` — ``count``/``error`` are branch-specific."""

    success: bool
    labels: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    error: str | None = None


class GmailLabelResource(BaseModel):
    """A Gmail ``labels`` resource, forwarded to the client verbatim.

    No field is declared on purpose: Gmail owns this schema, so ``extra="allow"``
    passes the payload through untouched instead of guessing at a structure that
    would silently drop provider fields. Mirrors ``GoogleCalendarEventResource``.
    """

    model_config = ConfigDict(extra="allow")


class GmailDraftResource(BaseModel):
    """A Gmail ``drafts`` resource, forwarded verbatim — see ``GmailLabelResource``."""

    model_config = ConfigDict(extra="allow")


class GmailLabelsResponse(BaseModel):
    """Response for ``GET /gmail/labels``."""

    labels: list[dict[str, Any]]
    count: int


class GmailEmailResult(BaseModel):
    """Return shape of ``get_email_by_id``."""

    success: bool
    message: dict[str, Any] | None = None
    error: str | None = None


class GmailMessageResponse(BaseModel):
    """Response for ``GET /gmail/message/{message_id}``."""

    message: dict[str, Any] | None
    status: str


class GmailThreadResponse(BaseModel):
    """Response for ``GET /gmail/thread/{thread_id}``.

    ``thread`` is the Composio thread payload with its messages transformed, so it
    keeps the provider's own envelope keys alongside ``messages``.
    """

    thread_id: str
    messages_count: int
    thread: dict[str, Any]


class SendEmailResponse(BaseModel):
    """Response for ``POST /gmail/send-json``."""

    message_id: str | None
    status: str


class SendEmailWithAttachmentsResponse(SendEmailResponse):
    """Response for ``POST /gmail/send``, which also reports the attachment count."""

    attachments_count: int


class GmailMessageActionResponse(BaseModel):
    """Shared envelope of the bulk message-action endpoints.

    Each endpoint adds the field naming the ids it acted on (``starred``,
    ``trashed``, …); those names are part of the client contract.
    """

    success: bool
    count: int
    status: str


class MarkAsReadResponse(GmailMessageActionResponse):
    marked_as_read: list[str]


class MarkAsUnreadResponse(GmailMessageActionResponse):
    marked_as_unread: list[str]


class StarEmailsResponse(GmailMessageActionResponse):
    starred: list[str]


class UnstarEmailsResponse(GmailMessageActionResponse):
    unstarred: list[str]


class TrashEmailsResponse(GmailMessageActionResponse):
    trashed: list[str]


class UntrashEmailsResponse(GmailMessageActionResponse):
    restored: list[str]


class ArchiveEmailsResponse(GmailMessageActionResponse):
    archived: list[str]


class MoveToInboxResponse(GmailMessageActionResponse):
    moved_to_inbox: list[str]


class ModifyLabelsResponse(GmailMessageActionResponse):
    """Response for both the apply-label and remove-label endpoints."""

    modified_messages: list[str]


class GmailDraftsResponse(BaseModel):
    """Return shape of ``list_drafts``, forwarded verbatim by ``GET /gmail/drafts``."""

    drafts: list[dict[str, Any]]
    next_page_token: str | None = Field(default=None, serialization_alias="nextPageToken")


class DraftMutationResponse(BaseModel):
    """Response for the draft create and update endpoints."""

    draft_id: str | None
    message_id: str | None
    status: str


class SendDraftResponse(BaseModel):
    """Response for ``POST /gmail/drafts/{draft_id}/send``."""

    message_id: str
    thread_id: str
    status: str
    successful: bool


class GmailDeletionResponse(BaseModel):
    """Response for the label and draft delete endpoints."""

    status: Literal["success", "error"]
    message: str
