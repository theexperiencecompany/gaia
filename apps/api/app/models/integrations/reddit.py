"""Reddit OAuth API payloads the Reddit tool reads.

Reference: https://www.reddit.com/dev/api/
"""

from collections.abc import Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class RedditAccount(BaseModel):
    """``GET /api/v1/me`` — the authenticated account."""

    model_config = ConfigDict(extra="ignore")

    name: str
    id: str
    link_karma: int
    comment_karma: int
    total_karma: int
    icon_img: str | None = None
    is_gold: bool = False


class RedditSubreddit(BaseModel):
    """A ``t5`` thing's ``data`` as ``/subreddits/mine/subscriber`` lists it."""

    model_config = ConfigDict(extra="ignore")

    display_name: str
    title: str
    subscribers: int


class RedditMessage(BaseModel):
    """A ``t4`` thing's ``data`` as ``/message/unread`` lists it.

    ``author`` is ``null`` for system and subreddit messages.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    subject: str
    author: str | None = None
    created_utc: float


ThingT = TypeVar("ThingT", bound=BaseModel)


class RedditThing(BaseModel, Generic[ThingT]):
    """One ``{kind, data}`` entry of a listing."""

    model_config = ConfigDict(extra="ignore")

    data: ThingT


class RedditListingData(BaseModel, Generic[ThingT]):
    model_config = ConfigDict(extra="ignore")

    children: Sequence[RedditThing[ThingT]] = Field(default_factory=list)


class RedditListing(BaseModel, Generic[ThingT]):
    """A ``kind: "Listing"`` envelope — every paginated Reddit endpoint answers one."""

    model_config = ConfigDict(extra="ignore")

    data: RedditListingData[ThingT]

    @property
    def things(self) -> list[ThingT]:
        return [child.data for child in self.data.children]


RedditSubredditListing = RedditListing[RedditSubreddit]
RedditMessageListing = RedditListing[RedditMessage]
