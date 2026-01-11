"""
Gmail trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


class GmailNewMessagePayload(BaseModel):
    """Payload for GMAIL_NEW_GMAIL_MESSAGE trigger."""

    attachment_list: list[Any] | None = Field(
        None, description="List of attachments in the message"
    )
    message_id: str | None = Field(None, description="Message ID")
    message_text: str | None = Field(None, description="Text content of the message")
    message_timestamp: str | None = Field(None, description="Timestamp of the message")
    payload: dict[str, Any] | None = Field(None, description="Full message payload")
    sender: str | None = Field(None, description="Sender email address")
    subject: str | None = Field(None, description="Email subject")
    thread_id: str | None = Field(None, description="Thread ID")


# =============================================================================
# Tool Output Schemas
# =============================================================================


class GmailMessage(BaseModel):
    """Single Gmail message from GMAIL_FETCH_EMAILS."""

    model_config = ConfigDict(extra="ignore")

    messageId: str | None = Field(None, alias="messageId")
    messageText: str | None = Field(None, alias="messageText")
    messageTimestamp: str | None = Field(None, alias="messageTimestamp")
    labelIds: list[str] = Field(default_factory=list, alias="labelIds")
    subject: str | None = None
    sender: str | None = Field(None, alias="from")
    preview: dict[str, Any] | None = None


class GmailFetchEmailsData(BaseModel):
    """Output data for GMAIL_FETCH_EMAILS tool."""

    model_config = ConfigDict(extra="ignore")

    messages: list[GmailMessage] = Field(default_factory=list)
