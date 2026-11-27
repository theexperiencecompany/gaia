"""The Gmail tools' chat cards: compose and sent drafts, fetched mail, a thread, and contacts."""

from pydantic import Field

from app.models.composio_schemas.gmail import GmailMessageContent
from app.schemas.common import ResponseModel


class AttachmentDisplay(ResponseModel):
    """One attached file as a card shows it; never its storage key."""

    name: str
    mimetype: str


class EmailComposeCard(ResponseModel):
    """One Gmail compose call as its card renders it; draft_id only on a draft that must be sent as stored."""

    to: list[str]
    subject: str | None
    body: str | None
    thread_id: str | None
    bcc: list[str]
    cc: list[str]
    is_html: bool | None
    attachments: list[AttachmentDisplay]
    draft_id: str | None = None


class EmailSentDraftCard(ResponseModel):
    """A stored draft Gmail sent."""

    message_id: str | None
    message: str
    timestamp: str | None
    recipients: list[str]
    subject: str | None


class EmailListItem(ResponseModel):
    """One fetched message in the email list card."""

    sender: str = Field(serialization_alias="from")
    subject: str
    time: str
    thread_id: str
    id: str


class EmailThreadItem(ResponseModel):
    """One message of the thread card; content is "" when Gmail sent no parts."""

    id: str | None
    sender: str | None = Field(serialization_alias="from")
    subject: str | None
    time: str | None
    snippet: str | None
    body: str | None
    content: GmailMessageContent | str


class EmailThreadCard(ResponseModel):
    """A Gmail thread with its messages."""

    thread_id: str | None
    messages: list[EmailThreadItem]
    messages_count: int | None


class ContactCard(ResponseModel):
    """A person flattened to their primary name, email and phone; People may send any as null."""

    name: str | None
    email: str | None
    phone: str | None
    resource_name: str | None
