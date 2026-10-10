"""Gmail tool payloads the Composio Gmail hooks read.

Two kinds of shape live here: the data payloads of the Gmail tools whose
results the hooks reshape (Composio documents only the data/error/successful
envelope, so every inner field is optional with the default the UI shows for
it), and the argument bags of the tools whose calls the hooks preview or
annotate. MIME-level message models live in composio_schemas.gmail.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.composio_schemas.gmail import GmailMessageContent
from app.models.composio_schemas.google_people import (
    GoogleContactsResponseData,
    GooglePeopleSearchResponseData,
)


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


class GmailThreadMessageView(BaseModel):
    """One message of a thread as ``mail_templates.thread_template`` shapes it
    (``minimal_message_template`` with both body formats)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = ""
    sender: str | None = Field(default="", alias="from")
    subject: str | None = ""
    time: str | None = ""
    snippet: str | None = ""
    body: str | None = ""
    content: GmailMessageContent | None = None


class GmailThreadView(BaseModel):
    """``thread_template``'s output: the thread id, its trimmed messages, and their count."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    messages: list[GmailThreadMessageView] = Field(default_factory=list)
    message_count: int | None = Field(default=0, alias="messageCount")


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
