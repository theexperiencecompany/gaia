"""Gmail tool payloads the Composio Gmail hooks read, and the views the mail templates make of them.

Three kinds of shape live here: the data payloads of the Gmail tools whose
results the hooks reshape (Composio documents only the data/error/successful
envelope, so every inner field is optional with the default the UI shows for
it), the trimmed views mail_templates builds from them for the agent, and the
argument bags of the tools whose calls the hooks preview or annotate.
MIME-level message models live in composio_schemas.gmail.
"""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.models.composio_schemas.gmail import GmailMessageContent
from app.models.composio_schemas.google_people import (
    GoogleContactsResponseData,
    GooglePeopleSearchResponseData,
)
from app.models.integrations.gmail_messages import RelayedGmailMessage


class GmailDraftCreatedData(BaseModel):
    """``GMAIL_CREATE_EMAIL_DRAFT`` — the new draft's id, which the compose card's Send needs."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None


class GmailAttachmentData(BaseModel):
    """``GMAIL_FETCH_ATTACHMENT`` — the metadata kept for the LLM; the base64 body is dropped."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    attachment_id: str | None = Field(default="", alias="attachmentId")
    filename: str | None = ""
    mime_type: str | None = Field(default="", alias="mimeType")
    size: int | None = 0


class GmailSentDraftMessage(BaseModel):
    """The ``message`` block of a ``GMAIL_SEND_DRAFT`` result."""

    model_config = ConfigDict(extra="ignore")

    to: list[str] | str | None = Field(default_factory=list)
    subject: str | None = ""


class GmailSentDraftData(BaseModel):
    """``GMAIL_SEND_DRAFT``.

    ``successful`` is read with two defaults: the sent card streams unless the
    key says otherwise, the LLM summary only when the key is present and true —
    hence ``model_fields_set`` in the hook rather than a single default here.
    """

    model_config = ConfigDict(extra="ignore")

    successful: bool | None = None
    id: str | None = ""
    timestamp: str | None = ""
    message: GmailSentDraftMessage | None = Field(default_factory=GmailSentDraftMessage)


class GmailContactsData(BaseModel):
    """``GMAIL_GET_CONTACTS`` — People ``connections`` plus the page's count and cursor."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    response_data: GoogleContactsResponseData | None = None
    total_people: int | None = Field(default=None, alias="totalPeople")
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class GmailSearchPeopleData(BaseModel):
    """``GMAIL_SEARCH_PEOPLE`` — People ``results``."""

    model_config = ConfigDict(extra="ignore")

    response_data: GooglePeopleSearchResponseData | None = None


class GmailThreadData(BaseModel):
    """A users.threads resource: GMAIL_FETCH_MESSAGE_BY_THREAD_ID's data, or Gmail's own via the proxy."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    messages: list[RelayedGmailMessage] = Field(default_factory=list)


class GmailDraftDetailData(BaseModel):
    """A users.drafts resource: GMAIL_GET_DRAFT's data, or one GMAIL_LIST_DRAFTS entry."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    message: RelayedGmailMessage | None = None


class GmailDraftListData(BaseModel):
    """``GMAIL_LIST_DRAFTS``; Gmail omits ``drafts`` when the mailbox has none."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    drafts: list[GmailDraftDetailData] | None = None
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class GmailThreadMessageView(BaseModel):
    """One message of a thread as ``minimal_message_template`` shapes it.

    The hook reads it back with every field defaulted, so a partial message
    still renders the thread card.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = ""
    thread_id: str | None = Field(
        default="", validation_alias="threadId", serialization_alias="threadId"
    )
    sender: str | None = Field(default="", validation_alias="from", serialization_alias="from")
    to: str | None = ""
    subject: str | None = ""
    snippet: str | None = ""
    time: str | None = ""
    is_read: bool = Field(default=False, validation_alias="isRead", serialization_alias="isRead")
    has_attachment: bool = Field(
        default=False, validation_alias="hasAttachment", serialization_alias="hasAttachment"
    )
    body: str | None = ""
    labels: list[str] = Field(default_factory=list)
    content: GmailMessageContent | None = Field(
        default=None, exclude_if=lambda content: content is None
    )


class GmailThreadView(BaseModel):
    """``thread_template``'s output: the thread id, its trimmed messages, and their count."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    messages: list[GmailThreadMessageView] = Field(default_factory=list)
    message_count: int | None = Field(
        default=0, validation_alias="messageCount", serialization_alias="messageCount"
    )


class GmailDraftMessageView(TypedDict):
    """A draft's message as ``draft_template`` trims it; body is the plain text."""

    to: str
    subject: str
    snippet: str
    body: str
    content: GmailMessageContent


class GmailDraftView(TypedDict):
    """``draft_template``'s output."""

    id: str
    message: GmailDraftMessageView


class GmailDraftListView(TypedDict):
    """``process_list_drafts_response``'s output; drafts appears only when Gmail sent them."""

    nextPageToken: str | None
    resultSize: int
    drafts: NotRequired[list[GmailDraftView]]


class GmailComposeArguments(BaseModel):
    """The compose-tool arguments the compose/sent card shows.

    Covers ``GMAIL_SEND_EMAIL``, ``GMAIL_CREATE_EMAIL_DRAFT``,
    ``GMAIL_REPLY_TO_THREAD`` and ``GMAIL_FORWARD_MESSAGE``: ``recipient_email`` /
    ``extra_recipients`` name the compose recipients, ``to_recipients`` the
    forward ones, and ``to`` is the field agents reach for instead of
    ``recipient_email`` (the hook maps it across). Every value may be null — the
    agent decides what it sends — and a string where a list belongs is tolerated
    the way the card always did (``to_recipients`` wraps it, ``extra_recipients``
    drops it).
    """

    model_config = ConfigDict(extra="ignore")

    recipient_email: str | None = ""
    to: str | list[str] | None = None
    extra_recipients: list[str] | str | None = Field(default_factory=list)
    to_recipients: list[str] | str | None = Field(default_factory=list)
    cc: list[str] | str | None = Field(default_factory=list)
    bcc: list[str] | str | None = Field(default_factory=list)
    subject: str | None = ""
    body: str | None = ""
    thread_id: str | None = ""
    is_html: bool | None = False


class GmailLabelArguments(BaseModel):
    """``GMAIL_CREATE_LABEL`` — the label name the progress line shows."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = ""


class GmailModifyLabelsArguments(BaseModel):
    """``GMAIL_ADD_LABEL_TO_EMAIL`` / ``GMAIL_REMOVE_LABEL`` — counted for the progress line."""

    model_config = ConfigDict(extra="ignore")

    message_ids: list[str] | str | None = Field(default_factory=list)
    label_ids: list[str] | str | None = Field(default_factory=list)


class GmailListDraftsArguments(BaseModel):
    """``GMAIL_LIST_DRAFTS``."""

    model_config = ConfigDict(extra="ignore")

    max_results: int | None = 20


class GmailGetContactsArguments(BaseModel):
    """``GMAIL_GET_CONTACTS``; the hook defaults ``page_size`` when unset."""

    model_config = ConfigDict(extra="ignore")

    page_size: int | None = None


class GmailSearchPeopleArguments(BaseModel):
    """``GMAIL_SEARCH_PEOPLE``."""

    model_config = ConfigDict(extra="ignore")

    query: str | None = ""
