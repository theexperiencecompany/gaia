"""
Slack trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/slack.ts
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


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


# =============================================================================
# Tool Output Schemas
# =============================================================================


class SlackChannel(BaseModel):
    """Slack channel info."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None


class SlackMessage(BaseModel):
    """Single Slack message from search results."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    username: str | None = None
    user: str | None = None
    channel: SlackChannel | None = None
    ts: str | None = None
    permalink: str | None = None


class SlackSearchMessagesData(BaseModel):
    """Output data for SLACK_SEARCH_MESSAGES tool."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    messages: dict[str, Any] = Field(default_factory=dict)

    def get_matches(self) -> list[dict[str, Any]]:
        """Get message matches from nested structure."""
        return self.messages.get("matches", [])
