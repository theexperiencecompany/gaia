"""
Slack tool schemas.

Reference: node_modules/@composio/core/generated/slack.ts

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from pydantic import BaseModel, ConfigDict, Field


class SlackListAllChannelsInput(BaseModel):
    """Input for SLACK_LIST_ALL_CHANNELS."""

    channel_name: str | None = Field(None, description="Filter by channel name")
    cursor: str | None = Field(None, description="Pagination cursor")
    exclude_archived: bool | None = Field(None, description="Exclude archived channels")
    limit: int = Field(1, description="Limit per page (1-1000)")
    types: str | None = Field(
        None, description="Channel types (public_channel, private_channel, etc)"
    )


class SlackChannel(BaseModel):
    """Slack channel model."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str | None = None
    name: str | None = None
    created: int | None = None
    creator: str | None = None
    is_archived: bool | None = None
    is_channel: bool | None = None
    is_general: bool | None = None
    is_private: bool | None = None
    is_im: bool | None = None
    is_mpim: bool | None = None
    num_members: int | None = None


class SlackResponseMetadata(BaseModel):
    """Slack response metadata for pagination."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    next_cursor: str | None = None


class SlackListAllChannelsData(BaseModel):
    """Data inside ToolExecutionResponse.data for SLACK_LIST_ALL_CHANNELS."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    channels: list[dict] = Field(default_factory=list)
    response_metadata: dict | None = None

    def get_channels(self) -> list[SlackChannel]:
        """Get channels as typed models."""
        return [
            SlackChannel.model_validate(c) for c in self.channels if isinstance(c, dict)
        ]

    @property
    def next_cursor(self) -> str | None:
        """Get next cursor for pagination."""
        if self.response_metadata:
            return self.response_metadata.get("next_cursor")
        return None
