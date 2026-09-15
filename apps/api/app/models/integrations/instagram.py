"""Instagram Graph API payloads the Instagram tool reads.

Reference: https://developers.facebook.com/docs/instagram-platform/reference
"""

from pydantic import BaseModel, ConfigDict, Field


class InstagramProfile(BaseModel):
    """``GET /me`` under the tool's ``fields`` projection.

    Graph omits a field rather than sending ``null`` when the token's
    permissions do not cover it; the counts default to ``0`` for that case.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    username: str | None = None
    account_type: str | None = None
    media_count: int = 0
    followers_count: int = 0
    follows_count: int = 0
    biography: str | None = None


class InstagramMedia(BaseModel):
    """One ``GET /me/media`` item; ``caption`` and the counts are omitted when absent."""

    model_config = ConfigDict(extra="ignore")

    id: str
    caption: str | None = None
    media_type: str | None = None
    timestamp: str | None = None
    like_count: int = 0
    comments_count: int = 0
    permalink: str | None = None


class InstagramMediaList(BaseModel):
    """``GET /me/media`` — a Graph edge: ``data`` holds the page."""

    model_config = ConfigDict(extra="ignore")

    data: list[InstagramMedia] = Field(default_factory=list)
