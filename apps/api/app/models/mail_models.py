from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class EmailRequest(BaseModel):  # type: ignore[explicit-any]
    prompt: str
    subject: str | None = None
    body: str | None = None
    writingStyle: str | None = None
    contentLength: str | None = None
    clarityOption: str | None = None


class ComposedEmailOutput(BaseModel):  # type: ignore[explicit-any]
    """Structured output of the AI email composer."""

    subject: str = Field(description="Generated email subject line")
    body: str = Field(description="Generated email body")


class SendEmailRequest(BaseModel):  # type: ignore[explicit-any]
    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None


class EmailReadStatusRequest(BaseModel):  # type: ignore[explicit-any]
    message_ids: list[str]


class EmailActionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request model for performing actions on emails like star, trash, archive."""

    message_ids: list[str]


class LabelRequest(BaseModel):  # type: ignore[explicit-any]
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


class ApplyLabelRequest(BaseModel):  # type: ignore[explicit-any]
    """Request model for applying or removing labels from messages."""

    message_ids: list[str]
    label_ids: list[str]


class DraftRequest(BaseModel):  # type: ignore[explicit-any]
    """Request model for creating or updating a draft email.

    ``body`` may be Markdown or HTML — the Composio Gmail hook converts
    Markdown to HTML before sending, so callers never need to choose.
    """

    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None


class MailDocument(UserScopedDocument):  # type: ignore[explicit-any]
    """An analyzed-email importance summary as stored in the mail collection.

    ``extra="allow"`` because the analyzer stores a variable set of summary fields
    that the read endpoints return verbatim; keeping them avoids dropping data.
    """

    model_config = ConfigDict(extra="allow")

    message_id: str
    is_important: bool = False
    analyzed_at: datetime | None = None


class MailUpdate(BaseModel):  # type: ignore[explicit-any]
    model_config = ConfigDict(extra="forbid")

    is_important: bool | None = None


class EmailImportanceSummariesResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/importance-summaries``.

    ``emails`` entries stay ``dict[str, object]`` because they are JSON dumps of
    ``MailDocument``, which allows analyzer-supplied extra fields that vary per email.
    """

    status: Literal["success"]
    emails: list[dict[str, object]]
    count: int
    filtered_by_importance: bool


class EmailImportanceSummaryResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/importance-summary/{message_id}``.

    ``email`` stays ``dict[str, object]`` for the same reason as
    ``EmailImportanceSummariesResponse.emails``.
    """

    status: Literal["success"]
    email: dict[str, object]


class BulkEmailImportanceSummariesResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``POST /gmail/importance-summaries/bulk``.

    ``emails`` values stay ``dict[str, object]`` for the same reason as
    ``EmailImportanceSummariesResponse.emails``.
    """

    status: Literal["success"]
    emails: dict[str, dict[str, object]]
    found_count: int
    missing_count: int
    found_message_ids: list[str]
    missing_message_ids: list[str]


# Every Gmail message, label and draft payload below stays ``dict[str, object]``:
# Google owns those schemas and ``transform_gmail_message`` spreads the raw
# Composio message before adding its derived keys, so the field set varies per
# message. Only the envelopes the API builds itself are modelled here.


class GmailAttachmentPayload(TypedDict):
    """One entry of the ``attachments`` parameter Composio's Gmail compose tools take."""

    filename: str | None
    content: bytes
    content_type: str | None


class GmailToolResult(BaseModel):  # type: ignore[explicit-any]
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
    data: dict[str, object] | None = None
    messages: list[dict[str, object]] | None = None
    labels: list[dict[str, object]] | None = None
    drafts: list[dict[str, object]] | None = None
    message: dict[str, object] | None = None
    id: str | None = None
    thread_id: str | None = Field(default=None, alias="threadId")
    next_page_token: str | None = Field(default=None, alias="nextPageToken")

    def as_payload(self) -> dict[str, object]:
        """The response exactly as the provider sent it — keys it omitted stay omitted."""
        return self.model_dump(exclude_unset=True, by_alias=True)


class GmailFetchEmailsData(BaseModel):  # type: ignore[explicit-any]
    """The ``data`` payload of a ``GMAIL_FETCH_EMAILS`` result."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    messages: list[dict[str, object]] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class GmailMessageResource(BaseModel):  # type: ignore[explicit-any]
    """A Gmail ``messages`` resource returned by the label-modification tools.

    Only ``id`` is declared — it is the one field every caller reads, and Gmail
    always sends it; the rest of the payload rides along via ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    id: str


class GmailMessagesResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/messages`` and ``GET /gmail/search``, and the return
    shape of ``search_messages``, which the routes forward unchanged."""

    messages: list[dict[str, object]]
    next_page_token: str | None = Field(default=None, serialization_alias="nextPageToken")


class GmailLabelsResult(BaseModel):  # type: ignore[explicit-any]
    """Return shape of ``list_labels`` — ``count``/``error`` are branch-specific."""

    success: bool
    labels: list[dict[str, object]] = Field(default_factory=list)
    count: int = 0
    error: str | None = None


class GmailLabelResource(BaseModel):  # type: ignore[explicit-any]
    """A Gmail ``labels`` resource, forwarded to the client verbatim.

    No field is declared on purpose: Gmail owns this schema, so ``extra="allow"``
    passes the payload through untouched instead of guessing at a structure that
    would silently drop provider fields. Mirrors ``GoogleCalendarEventResource``.
    """

    model_config = ConfigDict(extra="allow")


class GmailDraftResource(BaseModel):  # type: ignore[explicit-any]
    """A Gmail ``drafts`` resource, forwarded verbatim — see ``GmailLabelResource``."""

    model_config = ConfigDict(extra="allow")


class GmailLabelsResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/labels``."""

    labels: list[dict[str, object]]
    count: int


class GmailEmailResult(BaseModel):  # type: ignore[explicit-any]
    """Return shape of ``get_email_by_id``."""

    success: bool
    message: dict[str, object] | None = None
    error: str | None = None


class GmailMessageResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/message/{message_id}``."""

    message: dict[str, object] | None
    status: str


class GmailThreadResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``GET /gmail/thread/{thread_id}``.

    ``thread`` is the Composio thread payload with its messages transformed, so it
    keeps the provider's own envelope keys alongside ``messages``.
    """

    thread_id: str
    messages_count: int
    thread: dict[str, object]


class SendEmailResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``POST /gmail/send-json``."""

    message_id: str | None
    status: str


class SendEmailWithAttachmentsResponse(SendEmailResponse):  # type: ignore[explicit-any]
    """Response for ``POST /gmail/send``, which also reports the attachment count."""

    attachments_count: int


class GmailMessageActionResponse(BaseModel):  # type: ignore[explicit-any]
    """Shared envelope of the bulk message-action endpoints.

    Each endpoint adds the field naming the ids it acted on (``starred``,
    ``trashed``, …); those names are part of the client contract.
    """

    success: bool
    count: int
    status: str


class MarkAsReadResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    marked_as_read: list[str]


class MarkAsUnreadResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    marked_as_unread: list[str]


class StarEmailsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    starred: list[str]


class UnstarEmailsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    unstarred: list[str]


class TrashEmailsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    trashed: list[str]


class UntrashEmailsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    restored: list[str]


class ArchiveEmailsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    archived: list[str]


class MoveToInboxResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    moved_to_inbox: list[str]


class ModifyLabelsResponse(GmailMessageActionResponse):  # type: ignore[explicit-any]
    """Response for both the apply-label and remove-label endpoints."""

    modified_messages: list[str]


class GmailDraftsResponse(BaseModel):  # type: ignore[explicit-any]
    """Return shape of ``list_drafts``, forwarded verbatim by ``GET /gmail/drafts``."""

    drafts: list[dict[str, object]]
    next_page_token: str | None = Field(default=None, serialization_alias="nextPageToken")


class DraftMutationResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for the draft create and update endpoints."""

    draft_id: str | None
    message_id: str | None
    status: str


class SendDraftResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for ``POST /gmail/drafts/{draft_id}/send``."""

    message_id: str
    thread_id: str
    status: str
    successful: bool


class GmailDeletionResponse(BaseModel):  # type: ignore[explicit-any]
    """Response for the label and draft delete endpoints."""

    status: Literal["success", "error"]
    message: str
