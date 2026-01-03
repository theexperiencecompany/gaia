"""Pydantic models for Twitter custom tools."""

from typing import List, Optional

from pydantic import BaseModel, Field


class BatchFollowInput(BaseModel):
    """Input for batch follow operation on Twitter."""

    usernames: Optional[List[str]] = Field(
        None,
        description="List of Twitter usernames to follow (without @). Either usernames or user_ids must be provided.",
        max_length=100,
    )
    user_ids: Optional[List[str]] = Field(
        None,
        description="List of Twitter user IDs to follow. Either usernames or user_ids must be provided.",
        max_length=100,
    )


class BatchUnfollowInput(BaseModel):
    """Input for batch unfollow operation on Twitter. DESTRUCTIVE - requires consent."""

    usernames: Optional[List[str]] = Field(
        None,
        description="List of Twitter usernames to unfollow (without @). Either usernames or user_ids must be provided.",
        max_length=100,
    )
    user_ids: Optional[List[str]] = Field(
        None,
        description="List of Twitter user IDs to unfollow. Either usernames or user_ids must be provided.",
        max_length=100,
    )


class CreateThreadInput(BaseModel):
    """Input for creating a Twitter thread (multiple connected tweets)."""

    tweets: List[str] = Field(
        ...,
        description="List of tweet texts to post as a thread. Each will be posted as a reply to the previous one.",
        min_length=2,
        max_length=25,
    )
    media_ids: Optional[List[List[str]]] = Field(
        None,
        description="Optional list of media ID arrays, one per tweet. Use TWITTER_UPLOAD_MEDIA first to get media IDs.",
    )


class SearchUsersInput(BaseModel):
    """Input for searching Twitter users by name or bio content."""

    query: str = Field(
        ...,
        description="Search query - can be a name, company, bio keywords, or partial username",
        min_length=1,
        max_length=500,
    )
    max_results: int = Field(
        10,
        description="Maximum number of users to return",
        ge=1,
        le=50,
    )


class ScheduleTweetInput(BaseModel):
    """Input for scheduling a tweet for later posting."""

    text: str = Field(
        ...,
        description="The tweet text content (max 280 characters)",
        max_length=280,
    )
    scheduled_time: str = Field(
        ...,
        description="ISO 8601 datetime string for when to post (e.g., '2024-12-25T10:00:00Z')",
    )
    media_urls: Optional[List[str]] = Field(
        None,
        description="Optional list of media URLs to attach",
        max_length=4,
    )
    reply_to_tweet_id: Optional[str] = Field(
        None,
        description="Optional tweet ID to reply to",
    )
