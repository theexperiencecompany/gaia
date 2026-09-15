"""
Twitter-specific hooks using the enhanced decorator system.

These hooks implement schema modifiers for customizing tool descriptions,
before/after hooks for data processing, and frontend streaming via writer.
"""

from dataclasses import dataclass
from typing import TypedDict

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from app.constants.log_tags import LogTag
from app.models.integrations.composio_hooks import (
    ComposioToolCall,
    ComposioToolResponse,
    JsonSchemaNode,
)
from app.models.integrations.twitter import TwitterCreateTweetResponse
from app.models.integrations.twitter_hooks import (
    TwitterCreatePostArguments,
    TwitterHookTweet,
    TwitterHookUser,
    TwitterSearchArguments,
    TwitterTweetPage,
    TwitterUserLookupData,
    TwitterUserPage,
)
from shared.py.wide_events import log

from .registry import (
    AfterHookResponse,
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
)

_MAX_RESULTS_PARAM = "max_results"
_LLM_TEXT_LIMIT = 200
_LLM_TWEET_LIMIT = 10
_LLM_USER_LIMIT = 20
_UNKNOWN_AUTHOR_USERNAME = "unknown"
_UNKNOWN_AUTHOR_NAME = "Unknown"


class TweetSummary(TypedDict):
    """One tweet as the LLM sees it in a search page."""

    id: str
    text: str
    author_username: str
    author_name: str
    likes: int
    retweets: int


class TweetSearchSummary(TypedDict):
    tweets: list[TweetSummary]
    result_count: int
    has_more: bool


class TimelineTweetSummary(TypedDict):
    id: str
    text: str
    author: str
    likes: int


class TimelineSummary(TypedDict):
    tweets: list[TimelineTweetSummary]
    count: int


class UserLookupSummary(TypedDict):
    id: str
    username: str
    name: str
    followers: int
    following: int
    verified: bool | None


class UserLookupsSummary(TypedDict):
    users: list[UserLookupSummary]


class FollowUserSummary(TypedDict):
    id: str
    username: str
    name: str
    followers: int


class FollowListSummary(TypedDict):
    users: list[FollowUserSummary]
    count: int
    has_more: bool


class PostCreatedSummary(TypedDict):
    success: bool
    id: str
    text: str
    url: str


@dataclass(frozen=True, slots=True)
class _AuthoredTweet:
    """A tweet joined to its author from the page's includes, when X expanded one."""

    tweet: TwitterHookTweet
    author: TwitterHookUser | None


def _metrics_payload(obj: TwitterHookTweet | TwitterHookUser) -> dict[str, object]:
    """Return public_metrics exactly as X sent it, or {} when it was not requested."""
    return obj.public_metrics.model_dump(exclude_unset=True) if obj.public_metrics else {}


def _author_identity(author: TwitterHookUser | None) -> dict[str, object]:
    """Return the author fields every tweet card shows; a placeholder when X expanded no author."""
    if author is None:
        return {"username": _UNKNOWN_AUTHOR_USERNAME, "name": _UNKNOWN_AUTHOR_NAME}
    return {
        "id": author.id,
        "username": author.username,
        "name": author.name,
        "profile_image_url": author.profile_image_url,
        "verified": author.verified,
    }


def _search_tweet_card(item: _AuthoredTweet) -> dict[str, object]:
    """Render a search result as the chat card shows it, author bio and metrics included."""
    author = _author_identity(item.author)
    if item.author is not None:
        author["description"] = item.author.description
        author["public_metrics"] = _metrics_payload(item.author)
    return {
        "id": item.tweet.id,
        "text": item.tweet.text,
        "created_at": item.tweet.created_at,
        "author": author,
        "public_metrics": _metrics_payload(item.tweet),
        "conversation_id": item.tweet.conversation_id,
    }


def _timeline_tweet_card(item: _AuthoredTweet) -> dict[str, object]:
    return {
        "id": item.tweet.id,
        "text": item.tweet.text,
        "created_at": item.tweet.created_at,
        "author": _author_identity(item.author),
        "public_metrics": _metrics_payload(item.tweet),
    }


def _profile_card(user: TwitterHookUser) -> dict[str, object]:
    """Render a looked-up user as the profile card shows them."""
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "description": user.description,
        "profile_image_url": user.profile_image_url,
        "verified": user.verified,
        "public_metrics": _metrics_payload(user),
        "created_at": user.created_at,
        "location": user.location,
        "url": user.url,
    }


def _follow_card(user: TwitterHookUser) -> dict[str, object]:
    """Render a follower / followed user as the list card shows them."""
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "profile_image_url": user.profile_image_url,
        "verified": user.verified,
        "description": user.description,
        "public_metrics": _metrics_payload(user),
    }


def _with_authors(page: TwitterTweetPage) -> list[_AuthoredTweet]:
    users_by_id = {user.id: user for user in page.includes.users}
    return [_AuthoredTweet(tweet, users_by_id.get(tweet.author_id)) for tweet in page.data]


def _llm_text(text: str) -> str:
    return text[:_LLM_TEXT_LIMIT] + "..." if len(text) > _LLM_TEXT_LIMIT else text


def _likes(tweet: TwitterHookTweet) -> int:
    return tweet.public_metrics.like_count if tweet.public_metrics else 0


def _retweets(tweet: TwitterHookTweet) -> int:
    return tweet.public_metrics.retweet_count if tweet.public_metrics else 0


def _followers(user: TwitterHookUser) -> int:
    return user.public_metrics.followers_count if user.public_metrics else 0


def _following(user: TwitterHookUser) -> int:
    return user.public_metrics.following_count if user.public_metrics else 0


def _result_count(page: TwitterTweetPage, tweets: list[_AuthoredTweet]) -> int:
    """Return meta.result_count when X sent one, else the number of tweets on the page."""
    return page.meta.result_count if page.meta.result_count is not None else len(tweets)


@register_schema_modifier(tools=["TWITTER_RECENT_SEARCH"])
def twitter_search_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """
    Add X/Twitter search syntax tips to TWITTER_RECENT_SEARCH description.

    This helps LLMs construct more effective search queries.
    """
    search_tips = (
        "\n\n📝 X SEARCH SYNTAX (use in 'query' parameter):\n"
        "• from:username - tweets from specific user\n"
        "• to:username - tweets replying to user\n"
        "• @username - tweets mentioning user\n"
        "• #hashtag - tweets with specific hashtag\n"
        '• "exact phrase" - exact phrase match\n'
        "• -keyword - exclude keyword\n"
        "• is:retweet / -is:retweet - include/exclude retweets\n"
        "• is:reply / -is:reply - include/exclude replies\n"
        "• has:media / has:images / has:videos - filter by media\n"
        "• has:links - tweets with links\n"
        "• lang:en - filter by language\n"
        "• min_retweets:10 / min_faves:50 - engagement filters\n"
        "• since:2024-01-01 until:2024-12-31 - date range\n\n"
        "Example: 'from:elonmusk -is:retweet -is:reply' for original tweets only"
    )
    schema.description += search_tips
    return schema


@register_schema_modifier(tools=["TWITTER_FOLLOW_USER"])
def twitter_follow_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Add guidance to search for user first if username is unknown."""
    guidance = (
        "\n\n💡 USER DISCOVERY TIP: If the user doesn't provide a username:\n"
        "1. Use TWITTER_RECENT_SEARCH with the person's name to find their tweets\n"
        "2. Extract the author's user_id from search results\n"
        "3. Present matching users to the user for selection\n"
        "4. Then use this tool with the selected target_user_id"
    )
    schema.description += guidance
    return schema


@register_schema_modifier(tools=["TWITTER_CREATION_OF_A_POST"])
def twitter_create_post_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Add guidance for creating tweets with media and threads."""
    guidance = (
        "\n\n📱 POSTING TIPS:\n"
        "• For media: Upload first with TWITTER_UPLOAD_MEDIA, then use media_media_ids\n"
        "• For threads: Create first tweet, then reply with reply_in_reply_to_tweet_id\n"
        "• For quotes: Use quote_tweet_id to quote another tweet\n"
        "• Use polls: Provide poll_options (2-4 options) and poll_duration_minutes"
    )
    schema.description += guidance
    return schema


@register_schema_modifier(tools=["TWITTER_USER_HOME_TIMELINE_BY_USER_ID"])
def twitter_timeline_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Set sensible defaults for timeline requests."""
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    if input_params is None:
        return schema

    props = input_params.properties
    if props is None:
        return schema

    if (max_results := props.get(_MAX_RESULTS_PARAM)) is not None:
        max_results.default = 20

    schema.input_parameters = input_params.as_schema()
    return schema


@register_before_hook(tools=["TWITTER_CREATION_OF_A_POST"])
def twitter_create_post_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Stream post creation data to frontend for preview."""
    try:
        writer = get_stream_writer()
        if writer is None:
            return params

        arguments = TwitterCreatePostArguments.model_validate(
            ComposioToolCall.model_validate(params).arguments
        )

        # Build post preview data for frontend
        post_data = {
            "text": arguments.text,
            "quote_tweet_id": arguments.quote_tweet_id,
            "reply_to_tweet_id": arguments.reply_in_reply_to_tweet_id,
            "media_ids": arguments.media_media_ids,
            "poll_options": arguments.poll_options,
        }

        payload = {
            "twitter_post_preview": post_data,
        }
        writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_create_post_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["TWITTER_RECENT_SEARCH", "TWITTER_FULL_ARCHIVE_SEARCH"])
def twitter_search_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Send search progress to frontend."""
    try:
        writer = get_stream_writer()
        if writer is None:
            return params

        arguments = TwitterSearchArguments.model_validate(
            ComposioToolCall.model_validate(params).arguments
        )

        payload = {"progress": f"Searching tweets for: {arguments.query}..."}
        writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_search_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_after_hook(tools=["TWITTER_RECENT_SEARCH", "TWITTER_FULL_ARCHIVE_SEARCH"])
def twitter_search_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process search response and send tweet data to frontend."""
    log.set(twitter_tool=tool, toolkit=toolkit)
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        page = TwitterTweetPage.model_validate(raw)
        tweets = _with_authors(page)

        # Send to frontend
        if writer is not None and tweets:
            payload = {
                "twitter_search_data": {
                    "tweets": [_search_tweet_card(item) for item in tweets],
                    "result_count": _result_count(page, tweets),
                    "next_token": page.meta.next_token,
                },
            }
            writer(payload)

        # Return cleaned data for LLM (minimize tokens)
        llm_tweets: list[TweetSummary] = [
            {
                "id": item.tweet.id,
                "text": _llm_text(item.tweet.text),
                "author_username": item.author.username
                if item.author
                else _UNKNOWN_AUTHOR_USERNAME,
                "author_name": item.author.name if item.author else _UNKNOWN_AUTHOR_NAME,
                "likes": _likes(item.tweet),
                "retweets": _retweets(item.tweet),
            }
            for item in tweets[:_LLM_TWEET_LIMIT]
        ]

        summary: TweetSearchSummary = {
            "tweets": llm_tweets,
            "result_count": _result_count(page, tweets),
            "has_more": bool(page.meta.next_token),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_search_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER_USER_LOOKUP_BY_USERNAMES"])
def twitter_user_lookup_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process user lookup and stream profile data to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        # Handle both single user and multiple users; a payload without a
        # ``data`` envelope is the bare user object itself.
        users: list[TwitterHookUser]
        if isinstance(raw, dict) and "data" not in raw:
            users = [TwitterHookUser.model_validate(raw)] if raw else []
        else:
            user_data = TwitterUserLookupData.model_validate(raw).data
            users = user_data if isinstance(user_data, list) else [user_data] if user_data else []

        # Send to frontend
        if writer is not None and users:
            payload = {
                "twitter_user_data": [_profile_card(user) for user in users],
            }
            writer(payload)

        # Return for LLM
        summary: UserLookupsSummary = {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": u.name,
                    "followers": _followers(u),
                    "following": _following(u),
                    "verified": u.verified,
                }
                for u in users
            ]
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_user_lookup_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["TWITTER_USER_HOME_TIMELINE_BY_USER_ID"])
def twitter_timeline_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process timeline and stream tweets to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        tweets = _with_authors(TwitterTweetPage.model_validate(raw))

        # Send to frontend
        if writer is not None and tweets:
            payload = {
                "twitter_timeline_data": {
                    "tweets": [_timeline_tweet_card(item) for item in tweets],
                }
            }
            writer(payload)

        # Return cleaned for LLM
        summary: TimelineSummary = {
            "tweets": [
                {
                    "id": t.tweet.id,
                    "text": _llm_text(t.tweet.text),
                    "author": t.author.username if t.author else _UNKNOWN_AUTHOR_USERNAME,
                    "likes": _likes(t.tweet),
                }
                for t in tweets[:_LLM_TWEET_LIMIT]
            ],
            "count": len(tweets),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_timeline_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER_FOLLOWING_BY_USER_ID"])
def twitter_followers_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process followers/following list and stream to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        page = TwitterUserPage.model_validate(raw)
        users = page.data

        # Send to frontend
        if writer is not None and users:
            action = "followers" if "FOLLOWERS" in tool else "following"
            payload = {
                f"twitter_{action}_data": [_follow_card(user) for user in users],
            }
            writer(payload)

        # Return for LLM
        summary: FollowListSummary = {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": u.name,
                    "followers": _followers(u),
                }
                for u in users[:_LLM_USER_LIMIT]
            ],
            "count": len(users),
            "has_more": bool(page.meta.next_token),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_followers_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["TWITTER_CREATION_OF_A_POST"])
def twitter_post_created_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Send created post data to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        post = TwitterCreateTweetResponse.model_validate(raw).data
        url = f"https://twitter.com/i/status/{post.id}"

        if writer is not None:
            payload = {
                "twitter_post_created": {
                    "id": post.id,
                    "text": post.text,
                    "url": url,
                },
            }
            writer(payload)

        summary: PostCreatedSummary = {
            "success": True,
            "id": post.id,
            "text": post.text,
            "url": url,
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in twitter_post_created_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw
