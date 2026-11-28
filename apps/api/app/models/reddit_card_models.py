"""The reddit_data card's payload: what a Reddit tool read or wrote, discriminated on type."""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ResponseModel


class RedditCardSearchPost(ResponseModel):
    """A post a search matched; subreddit is prefixed (r/...) and selftext trimmed."""

    id: str
    title: str
    author: str
    subreddit: str
    score: int
    num_comments: int
    created_utc: int | float
    permalink: str
    url: str
    selftext: str


class RedditCardPost(ResponseModel):
    """One post in full; subreddit is prefixed (r/...)."""

    id: str
    title: str
    author: str
    subreddit: str
    score: int
    upvote_ratio: int | float
    num_comments: int
    created_utc: int | float
    selftext: str
    url: str
    permalink: str
    is_self: bool
    link_flair_text: str | None


class RedditCardComment(ResponseModel):
    """One comment on a post."""

    id: str
    author: str
    body: str
    score: int
    created_utc: int | float
    permalink: str
    is_submitter: bool


class RedditCardPostCreated(ResponseModel):
    """The post the user just created."""

    id: str | None
    url: str | None
    message: str
    permalink: str | None


class RedditCardCommentCreated(ResponseModel):
    """The comment the user just posted."""

    id: str | None
    message: str
    permalink: str | None


class RedditSearchCard(ResponseModel):
    """A search's matching posts."""

    type: Literal["search"] = "search"
    posts: list[RedditCardSearchPost]


class RedditPostCard(ResponseModel):
    """A post read in full."""

    type: Literal["post"] = "post"
    post: RedditCardPost


class RedditCommentsCard(ResponseModel):
    """A post's comments, capped for the card."""

    type: Literal["comments"] = "comments"
    comments: list[RedditCardComment]


class RedditPostCreatedCard(ResponseModel):
    """A post the user created."""

    type: Literal["post_created"] = "post_created"
    data: RedditCardPostCreated


class RedditCommentCreatedCard(ResponseModel):
    """A comment the user posted."""

    type: Literal["comment_created"] = "comment_created"
    data: RedditCardCommentCreated


RedditCardData = Annotated[
    RedditSearchCard
    | RedditPostCard
    | RedditCommentsCard
    | RedditPostCreatedCard
    | RedditCommentCreatedCard,
    Field(discriminator="type"),
]
