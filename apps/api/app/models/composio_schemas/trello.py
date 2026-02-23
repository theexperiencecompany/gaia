"""
Trello tool output models.

Reference: node_modules/@composio/core/generated/trello.ts
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrelloCard(BaseModel):
    """Single Trello card - minimal fields for LLM summarization."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    due: str | None = None


class TrelloCardsData(BaseModel):
    """Output data for TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER tool."""

    model_config = ConfigDict(extra="ignore")

    cards: list[TrelloCard] = Field(default_factory=list)

    @classmethod
    def from_response(cls, data: Any) -> "TrelloCardsData":
        """Create from response, handling list format."""
        if isinstance(data, list):
            return cls(cards=data)
        return cls.model_validate(data)
