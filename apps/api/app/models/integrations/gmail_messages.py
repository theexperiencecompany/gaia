"""Message shapes normalised by transform_gmail_message.

A Composio Gmail message (GMAIL_FETCH_EMAILS items) and a raw Gmail API
users.messages resource (thread fetches, drafts, single messages).
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
