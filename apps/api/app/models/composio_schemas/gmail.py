"""
Gmail trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.email import DEFAULT_SUMMARY_FIELDS, MessageFieldLiteral

# =============================================================================
# Trigger Payloads
# =============================================================================


class GmailNewMessagePayload(BaseModel):
    """Payload for GMAIL_NEW_GMAIL_MESSAGE trigger.

    Field set verified against Composio triggers_types API (2026-08).
    """

    attachment_list: list[Any] | None = Field(
        None, description="List of attachments in the message"
    )
    id: str | None = Field(None, description="The raw Gmail message ID")
    label_ids: list[str] | None = Field(
        None, description="The Gmail label IDs applied to the message"
    )
    message_id: str | None = Field(None, description="Message ID")
    message_text: str | None = Field(None, description="Text content of the message")
    message_timestamp: str | None = Field(None, description="Timestamp of the message")
    payload: dict[str, Any] | None = Field(None, description="Full message payload")
    preview: dict[str, Any] | None = Field(None, description="Preview payload of the message")
    sender: str | None = Field(None, description="Sender email address")
    subject: str | None = Field(None, description="Email subject")
    thread_id: str | None = Field(None, description="Thread ID")
    to: str | None = Field(None, description="Recipient email address")


# =============================================================================
# Custom Tool Inputs
# =============================================================================


# Convenience timeframes the agent can pass instead of computing Gmail's
# after:/before: operators. Resolved server-side using the user's home timezone.
TimeframeLiteral = Literal[
    "today",
    "yesterday",
    "tomorrow",
    "this_week",
    "last_week",
    "next_week",
    "1d",
    "3d",
    "5d",
    "7d",
    "1w",
    "2w",
    "1m",
    "3m",
    "6m",
    "1y",
]

BodyProcessingLiteral = Literal["normalize", "raw", "none"]


class FetchMessagesInput(BaseModel):
    """Input for the GMAIL_FETCH_MESSAGES custom tool."""

    timeframe: TimeframeLiteral | None = Field(
        default=None,
        description=(
            "Convenience range, resolved to Gmail's after:/before: operators "
            "in the user's home timezone. Ignored if `query` already "
            "contains after:/before:."
        ),
    )
    query: str | None = Field(
        default=None,
        description="Raw Gmail search query (ANDed with the timeframe clause).",
    )
    fields: list[MessageFieldLiteral] = Field(
        default_factory=lambda: list(DEFAULT_SUMMARY_FIELDS),
        description=(
            "Which fields per message. Defaults to metadata + snippet. "
            "Add 'body' for the processed body. Empty list = all fields."
        ),
    )

    @field_validator("fields", mode="before")
    @classmethod
    def _coerce_none_fields(
        cls, value: list[MessageFieldLiteral] | None
    ) -> list[MessageFieldLiteral]:
        # Tool wrappers pass omitted args as explicit None; treat that the same
        # as omission and fall back to the curated default field set. An empty
        # list is preserved (it carries the "all fields" meaning downstream).
        if value is None:
            return list(DEFAULT_SUMMARY_FIELDS)
        return value

    body_processing: BodyProcessingLiteral = Field(
        default="normalize",
        description=(
            "'normalize' (default): strip signatures, disclaimers, "
            "unsubscribe footers, and utm tracking chains. Lossless on "
            "meaningful content (quoted replies are KEPT — they give context "
            "into the older conversation). 'raw': untouched Gmail body. "
            "'none': omit body regardless of fields[]."
        ),
    )
    max_messages: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Cap on total messages aggregated. Default scales with timeframe "
            "(100 for today/yesterday, 200 for a week, 500 for a month+)."
        ),
    )
    per_page: int = Field(default=100, ge=1, le=500, description="Gmail page size (max 500).")


class FetchThreadInput(BaseModel):
    """Input for the GMAIL_FETCH_THREAD custom tool."""

    thread_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Gmail thread IDs to reconstruct, as a batch. Get them from the "
            "`threadId` on GMAIL_FETCH_MESSAGES results. Each thread is returned "
            "with its full message list in conversation order."
        ),
    )
    fields: list[MessageFieldLiteral] = Field(
        default_factory=lambda: list(DEFAULT_SUMMARY_FIELDS),
        description=(
            "Which fields per message. Defaults to metadata + snippet. "
            "Add 'body' for the processed body. Empty list = all fields."
        ),
    )

    @field_validator("fields", mode="before")
    @classmethod
    def _coerce_none_fields(
        cls, value: list[MessageFieldLiteral] | None
    ) -> list[MessageFieldLiteral]:
        if value is None:
            return list(DEFAULT_SUMMARY_FIELDS)
        return value

    body_processing: BodyProcessingLiteral = Field(
        default="normalize",
        description=(
            "'normalize' (default): strip signatures, disclaimers, unsubscribe "
            "footers, and utm tracking chains; quoted replies are KEPT. 'raw': "
            "untouched Gmail body. 'none': omit body regardless of fields[]."
        ),
    )
    max_messages: int | None = Field(
        default=None,
        ge=1,
        description="Cap on total messages across all requested threads.",
    )


# =============================================================================
# Gmail REST wire shapes
# =============================================================================
# Everything below models what the Gmail REST API itself returns through the
# Composio proxy (users.messages / users.threads / users.labels / getProfile).
# Every field is optional or defaulted because Gmail's response varies by
# ``format`` (``metadata`` omits the MIME tree entirely) and ``extra="allow"``
# keeps the fields we don't read rather than silently dropping them.


class GmailHeader(BaseModel):
    """One ``{name, value}`` entry of a MIME part's ``headers`` array."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    value: str = ""


class GmailPartBody(BaseModel):
    """A MIME part's ``body``: inline base64url ``data``, or an attachment reference."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    attachment_id: str | None = Field(default=None, alias="attachmentId")
    size: int | None = None
    data: str | None = None


class GmailMessagePart(BaseModel):
    """One node of a Gmail message's MIME tree.

    Recursive by construction: a ``multipart/*`` part nests further parts to
    arbitrary depth, so the tree is walked, never indexed at a fixed level.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    part_id: str | None = Field(default=None, alias="partId")
    mime_type: str | None = Field(default=None, alias="mimeType")
    filename: str | None = None
    headers: list[GmailHeader] = Field(default_factory=list)
    body: GmailPartBody | None = None
    parts: list["GmailMessagePart"] = Field(default_factory=list)


class GmailAttachmentMetadata(TypedDict):
    """One attachment as reported by a message view — metadata only, no bytes."""

    filename: str | None
    mimeType: str | None
    size: int | None
    attachmentId: str | None


class GmailParsedAttachment(TypedDict, total=False):
    """An attachment as reported by ``GmailMessageParser.attachments``.

    ``total=False`` because the two extraction paths report different key sets:
    the raw-payload fallback carries ``attachmentId`` (the id used to fetch the
    bytes later), while the parsed-MIME path already holds the decoded
    ``content``.
    """

    filename: str | None
    mimeType: str | None
    size: int | None
    attachmentId: str | None
    messageId: str
    content: bytes | None


class GmailMessageContent(TypedDict):
    """A message body in both renderings, as extracted from its MIME parts."""

    text: str
    html: str


class GmailMessageRef(BaseModel):
    """A ``{id, threadId}`` stub from ``users.messages.list``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = None
    thread_id: str | None = Field(default=None, alias="threadId")


class GmailMessagesListResponse(BaseModel):
    """``users.messages.list`` response — id stubs plus paging/count metadata."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    messages: list[GmailMessageRef] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    # Absent on an empty mailbox response; callers fall back to len(messages).
    result_size_estimate: int | None = Field(default=None, alias="resultSizeEstimate")


class GmailLabelDetail(BaseModel):
    """``users.labels.get`` response — the counts the unread-count tool reports."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = None
    name: str | None = None
    messages_total: int = Field(default=0, alias="messagesTotal")
    messages_unread: int = Field(default=0, alias="messagesUnread")


class GmailProfile(BaseModel):
    """``users.getProfile`` response."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    email_address: str | None = Field(default=None, alias="emailAddress")
    messages_total: int | None = Field(default=None, alias="messagesTotal")
    threads_total: int | None = Field(default=None, alias="threadsTotal")


# =============================================================================
# Custom Tool Result Shapes
# =============================================================================
# In-process contracts between the Gmail custom tools and their helpers. They
# are TypedDicts rather than models because nothing validates them at runtime —
# the tools build them and hand them straight to the agent as JSON.


class GmailReadRange(TypedDict):
    """A ``read(offset, limit)`` call over an offloaded JSONL file."""

    offset: int
    limit: int


class GmailReadChunk(TypedDict):
    """One contiguous line range of an offloaded JSONL file, for one subagent."""

    part: int
    start_line: int
    line_count: int
    read: GmailReadRange


class GmailReadPlan(TypedDict):
    """How an offloaded JSONL file should be split across parallel subagent reads."""

    total_lines: int
    recommended_subagents: int
    chunks: list[GmailReadChunk]


class GmailBatchModifyResult(TypedDict):
    """Outcome of a chunked ``users.messages.batchModify`` run.

    ``partial``/``error`` appear only when some chunks succeeded before a later
    one failed; a clean run reports counts alone.
    """

    modified_count: int
    failed_count: int
    partial: NotRequired[bool]
    error: NotRequired[str]


class GmailLabelCounts(TypedDict):
    """Per-label message counts reported by the unread-count tool.

    The camelCase keys are the agent-facing contract, matching Gmail's own
    ``messagesUnread``/``messagesTotal`` naming.
    """

    label_id: str
    label_name: str
    unreadCount: int
    totalCount: int
