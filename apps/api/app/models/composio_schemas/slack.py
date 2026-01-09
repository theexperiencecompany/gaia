"""
Slack trigger payload models.

Reference: node_modules/@composio/core/generated/slack.ts
"""

from typing import Any

from pydantic import BaseModel, Field


class SlackReceiveMessagePayload(BaseModel):
    """Payload for SLACK_RECEIVE_MESSAGE trigger."""

    attachments: list[dict[str, Any]] | None = Field(
        None, description="Attachments included with the message"
    )
    bot_id: str | None = Field(None, description="ID of the bot that posted")
    channel: str | None = Field(None, description="Channel ID where message was posted")
    channel_type: str | None = Field(None, description="Type of the channel")
    team_id: str | None = Field(None, description="Team ID")
    text: str | None = Field(None, description="Text content of the message")
    ts: str | None = Field(None, description="Timestamp of the message")
    user: str | None = Field(None, description="User ID who sent the message")


class SlackChannelCreatedPayload(BaseModel):
    """Payload for SLACK_CHANNEL_CREATED trigger."""

    created: int | None = Field(None, description="Unix timestamp when created")
    creator: str | None = Field(None, description="User ID who created the channel")
    id: str | None = Field(None, description="Channel ID")
    name: str | None = Field(None, description="Channel name")
