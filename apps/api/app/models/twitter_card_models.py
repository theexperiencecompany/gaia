"""The Twitter cards' payloads: looked-up profiles and searched tweets.

public_metrics is the count block exactly as X sent it, so its keys vary with what was requested.
"""

from app.schemas.common import ResponseModel


class TwitterUserCard(ResponseModel):
    """A user as the twitter_user_data profile card shows them."""

    id: str
    username: str
    name: str
    description: str | None
    profile_image_url: str | None
    verified: bool | None
    public_metrics: dict[str, int]
    created_at: str | None
    location: str | None
    url: str | None = None


class TwitterTweetAuthor(ResponseModel):
    """A tweet's author, expanded from the page's includes."""

    id: str
    username: str
    name: str
    profile_image_url: str | None
    verified: bool | None
    description: str | None
    public_metrics: dict[str, int]


class TwitterUnknownAuthor(ResponseModel):
    """The placeholder author of a tweet X expanded no author for."""

    username: str
    name: str


class TwitterSearchTweet(ResponseModel):
    """One tweet a search matched."""

    id: str
    text: str
    created_at: str | None
    author: TwitterTweetAuthor | TwitterUnknownAuthor
    public_metrics: dict[str, int]
    conversation_id: str | None


class TwitterSearchCard(ResponseModel):
    """The twitter_search_data card: a page of matching tweets and the cursor to the next."""

    tweets: list[TwitterSearchTweet]
    result_count: int
    next_token: str | None
