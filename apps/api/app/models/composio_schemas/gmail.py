"""
Gmail trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

from typing import Any, Literal, NotRequired, Self, TypedDict

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


class GmailEmailSentPayload(BaseModel):
    """Payload for GMAIL_EMAIL_SENT_TRIGGER at the pinned toolkit 20260107_00.

    Field set verified against Composio triggers_types API (2026-09); the pinned
    version carries no message body or attachment list.
    """

    bcc: str | None = Field(None, description="Bcc recipients")
    cc: str | None = Field(None, description="Cc recipients")
    message_id: str | None = Field(None, description="Gmail message ID")
    message_timestamp: str | None = Field(None, description="When it was sent, ISO 8601")
    payload: dict[str, Any] | None = Field(None, description="Raw Gmail payload")
    recipients: str | None = Field(
        None, description="Comma-separated list of all recipients (To, Cc, Bcc)"
    )
    sender: str | None = Field(None, description="Sender email address")
    subject: str | None = Field(None, description="Email subject")
    thread_id: str | None = Field(None, description="Gmail thread ID")
    to: str | None = Field(None, description="To recipients")


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
    offload: bool = Field(
        default=False,
        description=(
            "true: write every message to a JSONL file and return only its digest, "
            "however few match. For a scan you aggregate with query_json and never read."
        ),
    )


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


# Gmail REST wire shapes: what the Gmail REST API returns via the Composio
# proxy. Fields are optional/defaulted since response shape varies by `format`
# (`metadata` omits the MIME tree); extra="allow" keeps unread fields.


class GmailHeader(BaseModel):
    """One ``{name, value}`` entry of a MIME part's ``headers`` array."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    # Null on some Composio-relayed messages (see transform_gmail_message's regression test).
    value: str | None = None


class GmailPartBody(BaseModel):
    """A MIME part's ``body``: inline base64url ``data``, or an attachment reference."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    attachment_id: str | None = Field(default=None, alias="attachmentId")
    size: int | None = None
    data: str | None = None


class GmailResourceId(BaseModel):
    """A Gmail resource (message, draft) in a tool result, read only for its ``id``.

    Optional because Composio documents only the result envelope, not the Gmail
    resource inside it.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None


class GmailDraftEntry(BaseModel):
    """One ``GMAIL_LIST_DRAFTS`` draft, read only for the message it wraps."""

    model_config = ConfigDict(extra="ignore")

    message: dict[str, object] | None = None


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
    parts: list[Self] = Field(default_factory=list)


class GmailAttachmentMetadata(TypedDict):
    """One attachment as reported by a message view — metadata only, no bytes."""

    filename: str | None
    mimeType: str | None
    size: int | None
    attachmentId: str | None


class GmailMessageContent(TypedDict):
    """A message body in both renderings, as extracted from its MIME parts."""

    text: str
    html: str


class GmailMessageView(BaseModel):
    """One message as the detailed template and GMAIL_FETCH_MESSAGES shape it.

    A model rather than a TypedDict because its wire key ``from`` is a Python
    keyword; the agent sees it dumped by alias. body and content are left out
    of the dump when the body was never fetched.
    """

    id: str
    thread_id: str = Field(serialization_alias="threadId")
    sender: str = Field(serialization_alias="from")
    # One key per sender whatever its display name, so counts group by sender.
    from_address: str
    to: str
    subject: str
    snippet: str
    time: str
    is_read: bool = Field(serialization_alias="isRead")
    has_attachment: bool = Field(serialization_alias="hasAttachment")
    attachments: list[GmailAttachmentMetadata]
    labels: list[str]
    cc: str
    body: str | None = Field(default=None, exclude_if=lambda body: body is None)
    content: GmailMessageContent | None = Field(
        default=None, exclude_if=lambda content: content is None
    )


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


# Custom Tool Result Shapes: in-process contracts between Gmail custom tools
# and their helpers. TypedDicts, not models, because nothing validates them at
# runtime — tools build them and hand them straight to the agent as JSON.


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


class GmailStarResult(GmailBatchModifyResult):
    """GMAIL_STAR_EMAIL: the batchModify outcome, naming which way it went."""

    action: Literal["starred", "unstarred"]


class GmailUnreadQueryCounts(TypedDict):
    """GMAIL_GET_UNREAD_COUNT in query mode: estimates for a search, total and unread."""

    query: str
    label_ids: list[str]
    totalCount: int
    unreadCount: int
    is_estimate: bool
    label_id: NotRequired[str]


class GmailUnreadLabelCounts(TypedDict):
    """GMAIL_GET_UNREAD_COUNT in label mode; one label also gets its counts lifted to the top."""

    counts: dict[str, GmailLabelCounts]
    label_ids: list[str]
    label_id: NotRequired[str]
    label_name: NotRequired[str]
    unreadCount: NotRequired[int]
    totalCount: NotRequired[int]


class GmailContact(TypedDict):
    """One address found in a message's From/To/Cc/Reply-To headers."""

    name: str
    email: str


class GmailContactList(TypedDict):
    """GMAIL_GET_CONTACT_LIST: the deduplicated contacts, or the error that stopped the scan."""

    success: bool
    contacts: list[GmailContact]
    count: int
    error: NotRequired[str]


class GmailContextUser(TypedDict):
    """The mailbox owner, as users.getProfile reports them."""

    email: str | None
    messages_total: int | None
    threads_total: int | None


class GmailContextInbox(TypedDict):
    """The INBOX label's counts."""

    unread_count: int
    message_count: int


class GmailContextSnapshot(TypedDict):
    """GMAIL_CUSTOM_GATHER_CONTEXT: who the mailbox is, its inbox counts, and its newest ids."""

    user: GmailContextUser
    inbox: GmailContextInbox
    recent_message_ids: list[str]


class GmailFetchInlineResult(TypedDict):
    """A fetch returned whole, as projected messages.

    total_matched and hint appear only when a result too large to inline had
    no session to offload into and was cut to the messages that fit.
    """

    fetched_count: int
    truncated: bool
    messages: list[dict[str, object]]
    total_matched: NotRequired[int]
    hint: NotRequired[str]


class GmailFetchPartialResult(TypedDict):
    """A fetch that failed partway: the messages read before the error, and the error."""

    fetched_count: int
    truncated: bool
    partial: bool
    error: str
    note: str
    messages: list[dict[str, object]]


class GmailThreadResult(TypedDict):
    """One thread of a GMAIL_FETCH_THREAD result, its messages projected."""

    id: str
    message_count: int
    messages: list[dict[str, object]]


class GmailFetchThreadResult(TypedDict):
    """GMAIL_FETCH_THREAD returned whole, each thread's messages grouped under it."""

    fetched_threads: int
    total_messages: int
    truncated: bool
    threads: list[GmailThreadResult]
