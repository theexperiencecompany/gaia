"""Reddit API payloads the Composio Reddit hooks reshape for the UI and the LLM.

Builds on RedditThing in integrations.reddit; the Kinded models add the kind
discriminator (t3 post, t1 comment, more) and the listing cursors.

Reference: https://www.reddit.com/dev/api/
"""

from typing import Generic

from pydantic import BaseModel, ConfigDict, Field

from app.models.integrations.reddit import RedditThing, ThingT


class RedditPost(BaseModel):
    """A ``t3`` thing's ``data`` — the fields the post card and the LLM summary show.

    Reddit sends every string field as a string (``author`` is ``"[deleted]"``,
    never null); ``link_flair_text`` is null when the post carries no flair.
    ``created_utc`` arrives as a float, ``upvote_ratio`` too.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    author: str = ""
    subreddit: str = ""
    subreddit_name_prefixed: str = ""
    created_utc: int | float = 0
    score: int = 0
    upvote_ratio: int | float = 0
    num_comments: int = 0
    selftext: str = ""
    url: str = ""
    permalink: str = ""
    is_self: bool = False
    link_flair_text: str | None = None
    over_18: bool = False
    spoiler: bool = False
    locked: bool = False
    stickied: bool = False


class RedditComment(BaseModel):
    """A ``t1`` thing's ``data``. ``edited`` is ``false`` or the edit timestamp;
    ``distinguished`` is null unless a moderator/admin flagged the comment."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    author: str = ""
    body: str = ""
    created_utc: int | float = 0
    score: int = 0
    permalink: str = ""
    parent_id: str = ""
    link_id: str = ""
    subreddit: str = ""
    is_submitter: bool = False
    stickied: bool = False
    distinguished: str | None = None
    edited: bool | int | float = False


class RedditKindedThing(RedditThing[ThingT], Generic[ThingT]):
    """A listing child with its kind: t3 post, t1 comment, more stub."""

    kind: str | None = None


class RedditKindedListingData(BaseModel, Generic[ThingT]):
    """A listing's ``data`` with kinded children and the page cursors (a sibling of
    ``RedditListingData``: narrowing its inherited ``children`` list is unsound)."""

    model_config = ConfigDict(extra="ignore")

    children: list[RedditKindedThing[ThingT]] = Field(default_factory=list)
    after: str | None = None
    before: str | None = None


class RedditKindedListing(BaseModel, Generic[ThingT]):
    """A ``kind: "Listing"`` envelope of kinded things."""

    model_config = ConfigDict(extra="ignore")

    data: RedditKindedListingData[ThingT] = Field(default_factory=RedditKindedListingData)


RedditPostThing = RedditKindedThing[RedditPost]
RedditCommentThing = RedditKindedThing[RedditComment]
RedditPostListing = RedditKindedListing[RedditPost]
RedditCommentListing = RedditKindedListing[RedditComment]


class RedditPostDetail(BaseModel):
    """``REDDIT_RETRIEVE_REDDIT_POST`` — the post thing, its fields under ``data``."""

    model_config = ConfigDict(extra="ignore")

    data: RedditPost = Field(default_factory=RedditPost)


class RedditSearchData(BaseModel):
    """``REDDIT_SEARCH_ACROSS_SUBREDDITS`` — the search listing under ``search_results``."""

    model_config = ConfigDict(extra="ignore")

    search_results: RedditPostListing = Field(default_factory=RedditPostListing)


class RedditCommentsData(BaseModel):
    """``REDDIT_RETRIEVE_POST_COMMENTS`` when it answers a mapping: the comments listing
    under ``comments`` (the raw Reddit endpoint answers ``[post_listing, comments_listing]``)."""

    model_config = ConfigDict(extra="ignore")

    comments: RedditCommentListing = Field(default_factory=RedditCommentListing)


class RedditCreatedContent(BaseModel):
    """``REDDIT_CREATE_REDDIT_POST`` / ``REDDIT_POST_REDDIT_COMMENT`` — the new thing's ids."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = ""
    url: str | None = ""
    permalink: str | None = ""


class RedditCreatePostArguments(BaseModel):
    """The ``REDDIT_CREATE_REDDIT_POST`` argument the progress line shows."""

    model_config = ConfigDict(extra="ignore")

    subreddit: str | None = ""
