"""
Gmail trigger payload models.

Reference: node_modules/@composio/core/generated/gmail.ts
"""

from typing import Any

from pydantic import BaseModel, Field


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
