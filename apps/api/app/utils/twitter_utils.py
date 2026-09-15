"""Twitter API utility functions for custom tools.

These helpers wrap Twitter API v2 calls behind Composio's proxy. The proxy
attaches the user's OAuth token server-side; callers only supply user_id.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.models.integrations.composio import ProxyErrorMeta
from app.models.integrations.twitter import (
    TwitterCreatedTweet,
    TwitterCreateTweetRequest,
    TwitterCreateTweetResponse,
    TwitterFollowRequest,
    TwitterSearchResponse,
    TwitterTweetMedia,
    TwitterTweetReply,
    TwitterUser,
    TwitterUserLookupResponse,
    TwitterUserResponse,
)
from app.services.composio.proxy_client import ProxyMethod, ProxyRequest, proxy_request_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

TWITTER_API_BASE = "https://api.twitter.com/2"
TWITTER_TOOLKIT = "TWITTER"


@dataclass(slots=True, frozen=True)
class TwitterOutcome:
    """Whether one Twitter call went through; error is the provider's answer when it did not."""

    success: bool
    error: str | None = None


@dataclass(slots=True, frozen=True)
class TwitterTweetOutcome:
    """create_tweet's result: the created tweet, or the provider's error."""

    success: bool
    tweet: TwitterCreatedTweet | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class TwitterSearchOutcome:
    """search_tweets's result: the search payload, or the provider's error."""

    success: bool
    data: TwitterSearchResponse | None = None
    error: str | None = None


def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: BaseModel | None = None,
    query: dict[str, str | int] | None = None,
) -> object:
    """Send one Twitter request; the result is untyped because every endpoint answers its own shape."""
    return proxy_request_sync(
        ProxyRequest(
            user_id=user_id,
            toolkit=TWITTER_TOOLKIT,
            endpoint=endpoint,
            method=method,
            body=body.model_dump(exclude_none=True) if body is not None else None,
            query=query,
        )
    )


def _provider_error(e: AppError) -> str:
    return f"HTTP {e.status_code}: {ProxyErrorMeta.model_validate(e.meta).provider_response}"


def get_my_user_id(user_id: str) -> str | None:
    """Get the authenticated user's Twitter ID."""
    log.set(operation="twitter_get_my_user_id")
    try:
        return TwitterUserResponse.model_validate(
            _proxy(user_id, endpoint=f"{TWITTER_API_BASE}/users/me", method="GET")
        ).data.id
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error getting user ID",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


def lookup_user_by_username(user_id: str, username: str) -> TwitterUser | None:
    """Look up a user by username."""
    try:
        return TwitterUserLookupResponse.model_validate(
            _proxy(
                user_id,
                endpoint=f"{TWITTER_API_BASE}/users/by/username/{username.lstrip('@')}",
                method="GET",
                query={
                    "user.fields": (
                        "id,name,username,description,profile_image_url,verified,public_metrics"
                    ),
                },
            )
        ).data
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error looking up user",
            username=username,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


def follow_user(user_id: str, my_user_id: str, target_user_id: str) -> TwitterOutcome:
    try:
        _proxy(
            user_id,
            endpoint=f"{TWITTER_API_BASE}/users/{my_user_id}/following",
            method="POST",
            body=TwitterFollowRequest(target_user_id=target_user_id),
        )
        return TwitterOutcome(success=True)
    except AppError as e:
        return TwitterOutcome(success=False, error=_provider_error(e))
    except Exception as e:
        return TwitterOutcome(success=False, error=str(e))


def unfollow_user(user_id: str, my_user_id: str, target_user_id: str) -> TwitterOutcome:
    try:
        _proxy(
            user_id,
            endpoint=(f"{TWITTER_API_BASE}/users/{my_user_id}/following/{target_user_id}"),
            method="DELETE",
        )
        return TwitterOutcome(success=True)
    except AppError as e:
        return TwitterOutcome(success=False, error=_provider_error(e))
    except Exception as e:
        return TwitterOutcome(success=False, error=str(e))


def create_tweet(
    user_id: str,
    text: str,
    reply_to_tweet_id: str | None = None,
    media_ids: list[str] | None = None,
    quote_tweet_id: str | None = None,
) -> TwitterTweetOutcome:
    try:
        body = TwitterCreateTweetRequest(
            text=text,
            reply=TwitterTweetReply(in_reply_to_tweet_id=reply_to_tweet_id)
            if reply_to_tweet_id
            else None,
            media=TwitterTweetMedia(media_ids=media_ids) if media_ids else None,
            quote_tweet_id=quote_tweet_id or None,
        )
        created = TwitterCreateTweetResponse.model_validate(
            _proxy(user_id, endpoint=f"{TWITTER_API_BASE}/tweets", method="POST", body=body)
        )
        return TwitterTweetOutcome(success=True, tweet=created.data)
    except AppError as e:
        return TwitterTweetOutcome(success=False, error=_provider_error(e))
    except Exception as e:
        return TwitterTweetOutcome(success=False, error=str(e))


def search_tweets(
    user_id: str,
    query: str,
    max_results: int = 10,
) -> TwitterSearchOutcome:
    """Search recent tweets."""
    log.set(operation="twitter_search_tweets", search_query=query, max_results=max_results)
    try:
        data = TwitterSearchResponse.model_validate(
            _proxy(
                user_id,
                endpoint=f"{TWITTER_API_BASE}/tweets/search/recent",
                method="GET",
                query={
                    "query": query,
                    "max_results": min(max_results, 100),
                    "user.fields": (
                        "id,name,username,description,profile_image_url,verified,"
                        "public_metrics,created_at,location"
                    ),
                    "expansions": "author_id",
                },
            )
        )
        return TwitterSearchOutcome(success=True, data=data)
    except AppError as e:
        return TwitterSearchOutcome(success=False, error=_provider_error(e))
    except Exception as e:
        return TwitterSearchOutcome(success=False, error=str(e))
