"""Trello card payloads the context tool forwards.

Reference: https://developer.atlassian.com/cloud/trello/rest/api-group-members/#api-members-id-cards-get
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrelloCard(BaseModel):
    """A card — nothing is read, it is forwarded verbatim (passthrough)."""

    model_config = ConfigDict(extra="allow")


class TrelloCardList(BaseModel):
    """``TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER`` data — Trello's bare list, or ``{cards: [...]}``."""

    model_config = ConfigDict(extra="ignore")

    cards: list[TrelloCard] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        return {"cards": data} if isinstance(data, list) else data
