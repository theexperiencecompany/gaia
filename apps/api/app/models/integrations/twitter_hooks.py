"""X API v2 shapes the Composio Twitter hooks read, on top of integrations.twitter.

Subclasses only add fields or defaults; list-typed fields are redeclared on
sibling models, since narrowing them is unsound.

Reference: https://developer.x.com/en/docs/x-api/data-dictionary
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.integrations.twitter import (
    TwitterTweet,
    TwitterTweetPublicMetrics,
    TwitterUser,
)


class TwitterHookTweetPublicMetrics(TwitterTweetPublicMetrics):
    """Public metrics that allow extras, since the block is streamed verbatim to the client."""

    model_config = ConfigDict(extra="allow")


class TwitterHookUser(TwitterUser):
    """A user as the UI cards render it.

    An unrequested verified or description shows as False or an empty string, not null.
    """

    verified: bool | None = False
    description: str | None = ""
    url: str | None = None


class TwitterHookTweet(TwitterTweet):
    """A tweet with the author_id and conversation_id expansions the cards need."""

    author_id: str | None = None
    conversation_id: str | None = None
    public_metrics: TwitterHookTweetPublicMetrics | None = None


class TwitterHookIncludes(BaseModel):
    """``includes`` with the hook's richer user shape (a sibling of ``TwitterSearchIncludes``:
    narrowing an inherited ``list`` field is unsound, so it does not subclass it)."""

    model_config = ConfigDict(extra="ignore")

    users: list[TwitterHookUser] = Field(default_factory=list)


class TwitterPageMeta(BaseModel):
    """``meta`` of a paginated search / timeline / follow list."""

    model_config = ConfigDict(extra="ignore")

    result_count: int | None = None
    next_token: str | None = None


class TwitterTweetPage(BaseModel):
    """A page of tweets with author expansions: recent search, full-archive search, home timeline."""

    model_config = ConfigDict(extra="ignore")

    data: list[TwitterHookTweet] = Field(default_factory=list)
    includes: TwitterHookIncludes = Field(default_factory=TwitterHookIncludes)
    meta: TwitterPageMeta = Field(default_factory=TwitterPageMeta)


class TwitterUserPage(BaseModel):
    """A page of users: ``GET /2/users/{id}/followers`` and ``/following``."""

    model_config = ConfigDict(extra="ignore")

    data: list[TwitterHookUser] = Field(default_factory=list)
    meta: TwitterPageMeta = Field(default_factory=TwitterPageMeta)


class TwitterUserLookupData(BaseModel):
    """``data`` is one user (lookup by username) or a list (lookup by usernames)."""

    model_config = ConfigDict(extra="ignore")

    data: TwitterHookUser | list[TwitterHookUser] | None = None


class TwitterCreatePostArguments(BaseModel):
    """The ``TWITTER_CREATION_OF_A_POST`` arguments the post preview shows."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = ""
    quote_tweet_id: str | None = None
    reply_in_reply_to_tweet_id: str | None = None
    media_media_ids: list[str] | None = Field(default_factory=list)
    poll_options: list[str] | None = Field(default_factory=list)


class TwitterSearchArguments(BaseModel):
    """The ``TWITTER_RECENT_SEARCH`` / ``TWITTER_FULL_ARCHIVE_SEARCH`` arguments the progress line shows."""

    model_config = ConfigDict(extra="ignore")

    query: str | None = ""
