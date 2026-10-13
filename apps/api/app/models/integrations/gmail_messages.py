"""Gmail message shapes as they arrive from Gmail or a Composio Gmail tool.

A Composio Gmail message (GMAIL_FETCH_EMAILS items) and a raw Gmail API
users.messages resource (thread fetches, drafts, single messages), as
transform_gmail_message normalises them, plus the superset the mail
templates read.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.composio_schemas.gmail import GmailMessagePart


class GmailMessageTimestamps(BaseModel):
    """The timestamp fields either shape may carry, in ``get_time``'s precedence order."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: str | None = None
    message_timestamp: str | None = Field(default=None, alias="messageTimestamp")
    #: Gmail API epoch milliseconds, as a digit string.
    internal_date: str | None = Field(default=None, alias="internalDate")


class ComposioGmailMessage(GmailMessageTimestamps):
    """A Composio Gmail message.

    Every header field is nullable, and messageText is omitted under verbose=false.
    """

    message_id: str | None = Field(default=None, alias="messageId")
    thread_id: str | None = Field(default=None, alias="threadId")
    from_: str | None = Field(default=None, alias="from")
    sender: str | None = None
    to: str | None = None
    cc: str | None = None
    reply_to: str | None = Field(default=None, alias="replyTo")
    subject: str | None = None
    snippet: str | None = None
    message_text: str | None = Field(default=None, alias="messageText")
    body: str | None = None
    label_ids: list[str] | None = Field(default=None, alias="labelIds")


class GmailApiMessage(GmailMessageTimestamps):
    """A Gmail API users.messages resource; payload is the MIME tree."""

    id: str | None = None
    thread_id: str | None = Field(default=None, alias="threadId")
    label_ids: list[str] | None = Field(default=None, alias="labelIds")
    snippet: str | None = None
    payload: GmailMessagePart | None = None


class RelayedGmailMessage(GmailApiMessage):
    """A users.messages resource as the mail templates receive it, from Gmail or a Composio tool.

    Composio's copy adds headers flattened into top-level fields, which the
    templates fall back to when the MIME tree yields nothing. Each key is
    matched exactly as the wire spells it, never by its field name.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=False)

    #: The whole RFC 2822 message, base64url, when fetched with format=raw.
    raw: str | None = None
    message_id: str | None = Field(default=None, alias="messageId")
    sender: str | None = None
    to: str | None = None
    subject: str | None = None
    message_text: str | None = Field(default=None, alias="messageText")
    #: Composio's snake_case spelling; when present the parser reads it as the body.
    snake_case_message_text: str | None = Field(default=None, alias="message_text")
