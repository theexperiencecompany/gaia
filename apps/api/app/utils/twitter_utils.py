"""Twitter API utility functions for custom tools.

These helpers wrap Twitter API v2 calls behind Composio's proxy. The proxy
attaches the user's OAuth token server-side; callers only supply `user_id`.
"""

from typing import Any, Dict, List, Optional

from shared.py.wide_events import log
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError

TWITTER_API_BASE = "https://api.twitter.com/2"
TWITTER_TOOLKIT = "TWITTER"


def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Any:
    return proxy_request_sync(
        user_id=user_id,
        toolkit=TWITTER_TOOLKIT,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        body=body,
        query=query,
    )


def get_my_user_id(user_id: str) -> Optional[str]:
    """Get the authenticated user's Twitter ID."""
    log.set(operation="twitter_get_my_user_id")
    try:
        data = _proxy(user_id, endpoint=f"{TWITTER_API_BASE}/users/me", method="GET")
        return (data or {}).get("data", {}).get("id")
    except Exception as e:
        log.error(f"Error getting user ID: {e}")
        return None


def lookup_user_by_username(
    user_id: str, username: str
) -> Optional[Dict[str, Any]]:
    """Look up a user by username."""
    try:
        data = _proxy(
            user_id,
            endpoint=f"{TWITTER_API_BASE}/users/by/username/{username.lstrip('@')}",
            method="GET",
            query={
                "user.fields": (
                    "id,name,username,description,profile_image_url,verified,public_metrics"
                ),
            },
        )
        return (data or {}).get("data")
    except Exception as e:
        log.error(f"Error looking up user {username}: {e}")
        return None


def follow_user(
    user_id: str, my_user_id: str, target_user_id: str
) -> Dict[str, Any]:
    """Follow a user by ID."""
    try:
        data = _proxy(
            user_id,
            endpoint=f"{TWITTER_API_BASE}/users/{my_user_id}/following",
            method="POST",
            body={"target_user_id": target_user_id},
        )
        return {"success": True, "data": data}
    except AppError as e:
        return {
            "success": False,
            "error": f"HTTP {e.status_code}: {e.meta.get('provider_response')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def unfollow_user(
    user_id: str, my_user_id: str, target_user_id: str
) -> Dict[str, Any]:
    """Unfollow a user by ID."""
    try:
        data = _proxy(
            user_id,
            endpoint=(
                f"{TWITTER_API_BASE}/users/{my_user_id}/following/{target_user_id}"
            ),
            method="DELETE",
        )
        return {"success": True, "data": data}
    except AppError as e:
        return {
            "success": False,
            "error": f"HTTP {e.status_code}: {e.meta.get('provider_response')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_tweet(
    user_id: str,
    text: str,
    reply_to_tweet_id: Optional[str] = None,
    media_ids: Optional[List[str]] = None,
    quote_tweet_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a tweet."""
    try:
        body: Dict[str, Any] = {"text": text}
        if reply_to_tweet_id:
            body["reply"] = {"in_reply_to_tweet_id": reply_to_tweet_id}
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        if quote_tweet_id:
            body["quote_tweet_id"] = quote_tweet_id

        data = _proxy(
            user_id, endpoint=f"{TWITTER_API_BASE}/tweets", method="POST", body=body
        )
        return {"success": True, "data": (data or {}).get("data", {})}
    except AppError as e:
        return {
            "success": False,
            "error": f"HTTP {e.status_code}: {e.meta.get('provider_response')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_tweets(
    user_id: str,
    query: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """Search recent tweets."""
    log.set(
        operation="twitter_search_tweets", search_query=query, max_results=max_results
    )
    try:
        data = _proxy(
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
        return {"success": True, "data": data}
    except AppError as e:
        return {
            "success": False,
            "error": f"HTTP {e.status_code}: {e.meta.get('provider_response')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
