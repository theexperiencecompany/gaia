"""Slack search.messages payload the context tool reads and forwards.

Reference: https://docs.slack.dev/reference/methods/search.messages
"""

from pydantic import BaseModel, ConfigDict, Field


class SlackSearchMatch(BaseModel):
    """One ``messages.matches[]`` entry. Forwarded verbatim into the tool output — passthrough."""

    model_config = ConfigDict(extra="allow")

    ts: str
    text: str


class SlackSearchMessages(BaseModel):
    """The ``messages`` block of ``search.messages``."""

    model_config = ConfigDict(extra="ignore")

    matches: list[SlackSearchMatch] = Field(default_factory=list)


class SlackSearchResult(BaseModel):
    """``SLACK_SEARCH_MESSAGES`` data."""

    model_config = ConfigDict(extra="ignore")

    messages: SlackSearchMessages = Field(default_factory=SlackSearchMessages)
