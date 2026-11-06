"""
Gmail trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

import re
from typing import Annotated, Any, Literal, NotRequired, Self, TypedDict, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.constants.email import (
    DEFAULT_SUMMARY_FIELDS,
    MESSAGE_FIELD_SYNONYMS,
    MessageFieldLiteral,
)

# =============================================================================
# Trigger Payloads
# =============================================================================


class GmailNewMessagePayload(BaseModel):
    """Payload for GMAIL_NEW_GMAIL_MESSAGE trigger at the pinned toolkit 20261105_00.

    Field set verified against Composio triggers_types API (2026-11).
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


class GmailNewMessageEvent(GmailNewMessagePayload):
    """A new-message payload plus the signals GAIA derives from it at dispatch (gmail_signals.py).

    A signal the payload cannot back (no headers, no thread id) is absent, never false.
    """

    continues_thread: bool | None = Field(
        None, description="The message joins a thread that already had messages"
    )
    gmail_category: str | None = Field(None, description="Gmail's inbox tab label, CATEGORY_*")
    has_list_unsubscribe: bool | None = Field(None, description="Carries a List-Unsubscribe header")
    bulk_or_auto_submitted: bool | None = Field(
        None, description="Precedence bulk/list/junk, or Auto-Submitted other than no"
    )
    sender_looks_automated: bool | None = Field(
        None, description="The sender address reads as a no-reply or notification sender"
    )


class GmailEmailSentPayload(BaseModel):
    """Payload for GMAIL_EMAIL_SENT_TRIGGER at the pinned toolkit 20261105_00.

    Field set verified against Composio triggers_types API (2026-11).
    """

    attachment_list: list[Any] | None = Field(
        None, description="List of attachments in the message"
    )
    bcc: str | None = Field(None, description="Bcc recipients")
    cc: str | None = Field(None, description="Cc recipients")
    message_id: str | None = Field(None, description="Gmail message ID")
    message_text: str | None = Field(None, description="Text content of the message")
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
NamedTimeframeLiteral = Literal[
    "today",
    "yesterday",
    "tomorrow",
    "this_week",
    "last_week",
    "next_week",
]

#: "Last N days/weeks/months/years": 14d, 30d, 2w, 3m, 1y. Any count, because models
#: naturally ask for 14d or 30d and a closed list of counts refused them.
RELATIVE_TIMEFRAME_PATTERN = r"^[1-9][0-9]*[dwmy]$"
RelativeTimeframe = Annotated[str, StringConstraints(pattern=RELATIVE_TIMEFRAME_PATTERN)]

_TIMEFRAME_FORMS = (
    f"{', '.join(get_args(NamedTimeframeLiteral))}, or the last N days/weeks/months/years "
    "written <N>d / <N>w / <N>m / <N>y (2d, 7d, 14d, 30d, 2w, 3m, 1y)"
)


def _known_timeframe(value: object) -> object:
    """Refuse an unsupported timeframe with the forms that work, or a query to use instead."""
    if value is None or value in get_args(NamedTimeframeLiteral):
        return value
    if isinstance(value, str) and re.fullmatch(RELATIVE_TIMEFRAME_PATTERN, value):
        return value
    raise ValueError(
        f"timeframe {value!r} is not supported. Use one of: {_TIMEFRAME_FORMS}; "
        "for anything else (hours, a calendar month) put after:/before: in `query` instead."
    )


Timeframe = Annotated[NamedTimeframeLiteral | RelativeTimeframe, BeforeValidator(_known_timeframe)]


def _canonical_fields(value: object) -> object:
    """Read omitted fields as the default set and Gmail API spellings as the field they name.

    Tool wrappers pass an omitted arg as explicit None; an empty list is kept, it
    means "all fields". A non-list and unknown names pass through for the list
    and Literal checks to refuse.
    """
    if value is None:
        return list(DEFAULT_SUMMARY_FIELDS)
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        return value
    return list(dict.fromkeys(MESSAGE_FIELD_SYNONYMS.get(name, name) for name in value))


ProjectedFields = Annotated[list[MessageFieldLiteral], BeforeValidator(_canonical_fields)]

BodyProcessingLiteral = Literal["normalize", "raw", "none"]


class FetchMessagesInput(BaseModel):
    """Input for the GMAIL_FETCH_MESSAGES custom tool."""

    timeframe: Timeframe | None = Field(
        default=None,
        description=(
            "Convenience range, resolved to Gmail's after:/before: operators "
            "in the user's home timezone: today, yesterday, tomorrow, this_week, "
            "last_week, next_week, or the last N days/weeks/months/years as "
            "<N>d / <N>w / <N>m / <N>y (e.g. 2d, 14d, 30d, 2w, 3m, 1y). Ignored "
            "if `query` already contains after:/before:."
        ),
    )
    query: str | None = Field(
        default=None,
        description="Raw Gmail search query (ANDed with the timeframe clause).",
    )
    fields: ProjectedFields = Field(
        default_factory=lambda: list(DEFAULT_SUMMARY_FIELDS),
        description=(
            "Which fields per message. Defaults to metadata + snippet. "
            "Add 'body' for the processed body. Empty list = all fields."
        ),
    )

    body_processing: BodyProcessingLiteral = Field(
        default="normalize",
        description=(
            "'normalize' (default): strip signatures, disclaimers, "
            "unsubscribe footers, and utm tracking chains. Lossless on "
            "meaningful content (quoted replies are KEPT, they give context "
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
    fields: ProjectedFields = Field(
        default_factory=lambda: list(DEFAULT_SUMMARY_FIELDS),
        description=(
            "Which fields per message. Defaults to metadata + snippet. "
            "Add 'body' for the processed body. Empty list = all fields."
        ),
    )

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
    """A fetch returned whole: projected messages, or every field once compaction will file them."""

    fetched_count: int
    truncated: bool
    messages: list[dict[str, object]]


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
