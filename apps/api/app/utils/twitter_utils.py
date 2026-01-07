"""Twitter API utility functions for custom tools.

These are helper functions used by Twitter custom tools to interact with
the Twitter API v2 using OAuth 2.0 bearer tokens.
"""

from typing import Any, Dict, List, Optional

import httpx

from app.config.loggers import chat_logger as logger

TWITTER_API_BASE = "https://api.twitter.com/2"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=60)


def get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def twitter_headers(access_token: str) -> Dict[str, str]:
    """Return headers for Twitter API v2 requests."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def get_my_user_id(access_token: str) -> Optional[str]:
    """Get the authenticated user's ID."""
    try:
        resp = _http_client.get(
            f"{TWITTER_API_BASE}/users/me",
            headers=twitter_headers(access_token),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("id")
    except Exception as e:
        logger.error(f"Error getting user ID: {e}")
        return None


def lookup_user_by_username(
    access_token: str, username: str
) -> Optional[Dict[str, Any]]:
    """Look up a user by username."""
    try:
        resp = _http_client.get(
            f"{TWITTER_API_BASE}/users/by/username/{username.lstrip('@')}",
            headers=twitter_headers(access_token),
            params={
                "user.fields": "id,name,username,description,profile_image_url,verified,public_metrics"
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data")
    except Exception as e:
        logger.error(f"Error looking up user {username}: {e}")
        return None


def follow_user(
    access_token: str, my_user_id: str, target_user_id: str
) -> Dict[str, Any]:
    """Follow a user by ID."""
    try:
        resp = _http_client.post(
            f"{TWITTER_API_BASE}/users/{my_user_id}/following",
            headers=twitter_headers(access_token),
            json={"target_user_id": target_user_id},
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def unfollow_user(
    access_token: str, my_user_id: str, target_user_id: str
) -> Dict[str, Any]:
    """Unfollow a user by ID."""
    try:
        resp = _http_client.delete(
            f"{TWITTER_API_BASE}/users/{my_user_id}/following/{target_user_id}",
            headers=twitter_headers(access_token),
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_tweet(
    access_token: str,
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

        resp = _http_client.post(
            f"{TWITTER_API_BASE}/tweets",
            headers=twitter_headers(access_token),
            json=body,
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json().get("data", {})}
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_tweets(
    access_token: str,
    query: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """Search recent tweets."""
    try:
        resp = _http_client.get(
            f"{TWITTER_API_BASE}/tweets/search/recent",
            headers=twitter_headers(access_token),
            params={
                "query": query,
                "max_results": min(max_results, 100),
                "user.fields": "id,name,username,description,profile_image_url,verified,public_metrics,created_at,location",
                "expansions": "author_id",
            },
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
