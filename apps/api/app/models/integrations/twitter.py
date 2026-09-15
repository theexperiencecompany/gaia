"""Twitter/X API v2 payloads the Twitter tools read and send.

Reference: https://developer.x.com/en/docs/x-api/data-dictionary
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class TwitterUserPublicMetrics(BaseModel):
    """A user's ``public_metrics`` expansion.

    ``extra="allow"``: the search tool streams the block verbatim to the client
    (``twitter_user_data``), so metrics X adds later still reach it.
    """

    model_config = ConfigDict(extra="allow")

    followers_count: int = 0
    following_count: int = 0
    tweet_count: int = 0
    listed_count: int = 0


class TwitterUser(BaseModel):
    """A user object; ``id``/``name``/``username`` are always present, the rest only when requested."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    username: str
    description: str | None = None
    profile_image_url: str | None = None
    verified: bool | None = None
    public_metrics: TwitterUserPublicMetrics | None = None
    created_at: str | None = None
    location: str | None = None


class TwitterUserResponse(BaseModel):
    """``GET /2/users/me`` — a single-user lookup always carries ``data``."""

    model_config = ConfigDict(extra="ignore")

    data: TwitterUser


class TwitterUserLookupResponse(BaseModel):
    """``GET /2/users/by/username/{username}`` — an unknown handle answers 200 with ``errors`` and no ``data``."""

    model_config = ConfigDict(extra="ignore")

    data: TwitterUser | None = None


class TwitterTweetPublicMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    like_count: int = 0
    retweet_count: int = 0


class TwitterTweet(BaseModel):
    """A tweet object; ``created_at``/``public_metrics`` only when requested via ``tweet.fields``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str
    created_at: str | None = None
    public_metrics: TwitterTweetPublicMetrics | None = None


class TwitterTimelineResponse(BaseModel):
    """``GET /2/users/{id}/tweets`` — ``data`` is omitted when the user has no tweets."""

    model_config = ConfigDict(extra="ignore")

    data: list[TwitterTweet] = Field(default_factory=list)


class TwitterSearchIncludes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    users: Sequence[TwitterUser] = Field(default_factory=list)


class TwitterSearchResponse(BaseModel):
    """``GET /2/tweets/search/recent`` — ``data``/``includes`` are omitted when nothing matched."""

    model_config = ConfigDict(extra="ignore")

    data: Sequence[TwitterTweet] = Field(default_factory=list)
    includes: TwitterSearchIncludes = Field(default_factory=TwitterSearchIncludes)


class TwitterCreatedTweet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    text: str


class TwitterCreateTweetResponse(BaseModel):
    """``POST /2/tweets``."""

    model_config = ConfigDict(extra="ignore")

    data: TwitterCreatedTweet


class TwitterTweetReply(BaseModel):
    in_reply_to_tweet_id: str


class TwitterTweetMedia(BaseModel):
    media_ids: list[str]


class TwitterCreateTweetRequest(BaseModel):
    """``POST /2/tweets`` body; optional blocks are sent only when set."""

    text: str
    reply: TwitterTweetReply | None = None
    media: TwitterTweetMedia | None = None
    quote_tweet_id: str | None = None


class TwitterFollowRequest(BaseModel):
    """``POST /2/users/{id}/following`` body."""

    target_user_id: str
