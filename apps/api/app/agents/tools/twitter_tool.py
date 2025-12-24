"""Twitter custom tools using Composio custom tool infrastructure.

These tools provide enhanced Twitter functionality using direct X/Twitter API v2 calls.
Uses access_token from Composio's auth_credentials.

Custom tools:
- CUSTOM_BATCH_FOLLOW: Follow multiple users at once
- CUSTOM_BATCH_UNFOLLOW: Unfollow multiple users at once
- CUSTOM_CREATE_THREAD: Create tweet threads in one call
- CUSTOM_SEARCH_USERS: Find users by name/bio when username unknown
- CUSTOM_SCHEDULE_TWEET: Schedule a tweet for later (draft)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List, Optional

from app.decorators.documentation import with_doc
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)
from app.templates.docstrings.twitter_tool_docs import (
    CUSTOM_BATCH_FOLLOW_DOC,
    CUSTOM_BATCH_UNFOLLOW_DOC,
    CUSTOM_CREATE_THREAD_DOC,
    CUSTOM_SCHEDULE_TWEET_DOC,
    CUSTOM_SEARCH_USERS_DOC,
)
from app.utils.twitter_utils import (
    TWITTER_API_BASE,
    create_tweet,
    follow_user,
    get_access_token,
    get_my_user_id,
    lookup_user_by_username,
    search_tweets,
    twitter_headers,
    unfollow_user,
)
from composio import Composio
from langgraph.config import get_stream_writer


def register_twitter_custom_tools(composio: Composio) -> List[str]:
    """Register Twitter custom tools with Composio.

    Args:
        composio: The Composio client instance

    Returns:
        List of registered tool names
    """
    # Import httpx client from utils for username lookup
    from app.utils.twitter_utils import _http_client

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_BATCH_FOLLOW_DOC)
    def CUSTOM_BATCH_FOLLOW(
        request: BatchFollowInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Follow multiple Twitter users at once."""
        writer = get_stream_writer()
        access_token = get_access_token(auth_credentials)

        my_user_id = get_my_user_id(access_token)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results: List[Dict[str, Any]] = []
        success_count = 0
        failed_count = 0

        user_ids_to_process: List[Dict[str, Any]] = []

        if request.user_ids:
            for uid in request.user_ids:
                user_ids_to_process.append({"user_id": uid, "username": None})

        if request.usernames:
            for username in request.usernames:
                user_data = lookup_user_by_username(access_token, username)
                if user_data and user_data.get("id"):
                    user_ids_to_process.append(
                        {
                            "user_id": user_data["id"],
                            "username": user_data.get("username"),
                            "name": user_data.get("name"),
                        }
                    )
                else:
                    results.append(
                        {
                            "username": username,
                            "success": False,
                            "error": "User not found",
                        }
                    )
                    failed_count += 1

        total = len(user_ids_to_process)
        if writer is not None:
            writer({"progress": f"Following {total} users..."})

        for i, user_info in enumerate(user_ids_to_process):
            result = follow_user(access_token, my_user_id, user_info["user_id"])

            if result["success"]:
                results.append(
                    {
                        "user_id": user_info["user_id"],
                        "username": user_info.get("username"),
                        "success": True,
                    }
                )
                success_count += 1
            else:
                results.append(
                    {
                        "user_id": user_info["user_id"],
                        "username": user_info.get("username"),
                        "success": False,
                        "error": result.get("error"),
                    }
                )
                failed_count += 1

            if writer is not None and (i + 1) % 5 == 0:
                writer({"progress": f"Followed {i + 1}/{total} users..."})

        # If all operations failed, raise
        if results and failed_count == len(results):
            raise RuntimeError(f"Failed to follow all users: {results}")

        return {
            "results": results,
            "followed_count": success_count,
            "failed_count": failed_count,
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_BATCH_UNFOLLOW_DOC)
    def CUSTOM_BATCH_UNFOLLOW(
        request: BatchUnfollowInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Unfollow multiple Twitter users at once. DESTRUCTIVE - requires user consent."""
        writer = get_stream_writer()
        access_token = get_access_token(auth_credentials)

        my_user_id = get_my_user_id(access_token)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results: List[Dict[str, Any]] = []
        success_count = 0
        failed_count = 0

        user_ids_to_process: List[Dict[str, Any]] = []

        if request.user_ids:
            for uid in request.user_ids:
                user_ids_to_process.append({"user_id": uid, "username": None})

        if request.usernames:
            for username in request.usernames:
                user_data = lookup_user_by_username(access_token, username)
                if user_data and user_data.get("id"):
                    user_ids_to_process.append(
                        {
                            "user_id": user_data["id"],
                            "username": user_data.get("username"),
                        }
                    )
                else:
                    results.append(
                        {
                            "username": username,
                            "success": False,
                            "error": "User not found",
                        }
                    )
                    failed_count += 1

        total = len(user_ids_to_process)
        if writer is not None:
            writer({"progress": f"Unfollowing {total} users..."})

        for i, user_info in enumerate(user_ids_to_process):
            result = unfollow_user(access_token, my_user_id, user_info["user_id"])

            if result["success"]:
                results.append(
                    {
                        "user_id": user_info["user_id"],
                        "username": user_info.get("username"),
                        "success": True,
                    }
                )
                success_count += 1
            else:
                results.append(
                    {
                        "user_id": user_info["user_id"],
                        "username": user_info.get("username"),
                        "success": False,
                        "error": result.get("error"),
                    }
                )
                failed_count += 1

            if writer is not None and (i + 1) % 5 == 0:
                writer({"progress": f"Unfollowed {i + 1}/{total} users..."})

        # If all operations failed, raise
        if results and failed_count == len(results):
            raise RuntimeError(f"Failed to unfollow all users: {results}")

        return {
            "results": results,
            "unfollowed_count": success_count,
            "failed_count": failed_count,
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_CREATE_THREAD_DOC)
    def CUSTOM_CREATE_THREAD(
        request: CreateThreadInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a Twitter thread (multiple connected tweets)."""
        writer = get_stream_writer()
        access_token = get_access_token(auth_credentials)

        if len(request.tweets) < 2:
            raise ValueError("Thread must have at least 2 tweets")

        tweet_ids: List[str] = []
        previous_tweet_id: Optional[str] = None

        total_tweets = len(request.tweets)
        if writer is not None:
            writer({"progress": f"Creating thread with {total_tweets} tweets..."})

        for i, tweet_text in enumerate(request.tweets):
            media_ids = None
            if request.media_ids and i < len(request.media_ids):
                media_ids = request.media_ids[i] if request.media_ids[i] else None

            result = create_tweet(
                access_token,
                tweet_text,
                reply_to_tweet_id=previous_tweet_id,
                media_ids=media_ids,
            )

            if not result["success"]:
                raise RuntimeError(
                    f"Failed at tweet {i + 1}: {result.get('error')}. "
                    f"Partial tweet IDs: {tweet_ids}"
                )

            tweet_id = result["data"].get("id")
            if not tweet_id:
                raise RuntimeError(
                    f"No ID returned for tweet {i + 1}. Partial tweet IDs: {tweet_ids}"
                )

            tweet_ids.append(tweet_id)
            previous_tweet_id = tweet_id

            if writer is not None:
                writer({"progress": f"Posted tweet {i + 1}/{total_tweets}..."})

        # Get username for thread URL
        try:
            resp = _http_client.get(
                f"{TWITTER_API_BASE}/users/me",
                headers=twitter_headers(access_token),
            )
            resp.raise_for_status()
            username = resp.json().get("data", {}).get("username", "i")
        except Exception:
            username = "i"

        thread_url = f"https://twitter.com/{username}/status/{tweet_ids[0]}"

        if writer is not None:
            writer(
                {
                    "twitter_thread_created": {
                        "thread_id": tweet_ids[0],
                        "tweet_count": len(tweet_ids),
                        "url": thread_url,
                    }
                }
            )

        return {
            "thread_id": tweet_ids[0],
            "tweet_ids": tweet_ids,
            "tweet_count": len(tweet_ids),
            "thread_url": thread_url,
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_SEARCH_USERS_DOC)
    def CUSTOM_SEARCH_USERS(
        request: SearchUsersInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Search for Twitter users by name, bio, or keywords."""
        writer = get_stream_writer()
        access_token = get_access_token(auth_credentials)

        if writer is not None:
            writer({"progress": f"Searching for users matching: {request.query}..."})

        search_query = f"{request.query} -is:retweet"
        result = search_tweets(
            access_token, search_query, max_results=request.max_results * 3
        )

        if not result["success"]:
            raise RuntimeError(f"Search failed: {result.get('error')}")

        data = result["data"]
        includes = data.get("includes", {})
        api_users = includes.get("users", [])

        users_map: Dict[str, Dict[str, Any]] = {}
        for user in api_users:
            user_id = user.get("id")
            if user_id and user_id not in users_map:
                users_map[user_id] = {
                    "id": user_id,
                    "username": user.get("username"),
                    "name": user.get("name"),
                    "description": user.get("description", ""),
                    "profile_image_url": user.get("profile_image_url"),
                    "verified": user.get("verified", False),
                    "public_metrics": user.get("public_metrics", {}),
                    "created_at": user.get("created_at"),
                    "location": user.get("location"),
                }

        unique_users = list(users_map.values())[: request.max_results]

        if writer is not None and unique_users:
            writer({"twitter_user_data": unique_users})

        return {
            "users": [
                {
                    "id": u["id"],
                    "username": u.get("username"),
                    "name": u.get("name"),
                    "description": u.get("description", "")[:150],
                    "followers": u.get("public_metrics", {}).get("followers_count", 0),
                    "verified": u.get("verified", False),
                }
                for u in unique_users
            ],
            "count": len(unique_users),
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_SCHEDULE_TWEET_DOC)
    def CUSTOM_SCHEDULE_TWEET(
        request: ScheduleTweetInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Schedule a tweet for later posting (creates a draft with scheduled time).

        Note: Twitter API doesn't support scheduled tweets directly for free tier.
        This creates a draft that can be stored and posted later by a scheduler.
        """
        writer = get_stream_writer()

        draft = {
            "text": request.text,
            "scheduled_time": request.scheduled_time,
            "media_urls": request.media_urls,
            "reply_to_tweet_id": request.reply_to_tweet_id,
        }

        if writer is not None:
            writer({"twitter_scheduled_draft": draft})

        return {
            "draft": draft,
            "message": f"Tweet scheduled for {request.scheduled_time}. Note: Actual scheduling requires a backend scheduler service.",
        }

    return [
        "TWITTER_CUSTOM_BATCH_FOLLOW",
        "TWITTER_CUSTOM_BATCH_UNFOLLOW",
        "TWITTER_CUSTOM_CREATE_THREAD",
        "TWITTER_CUSTOM_SEARCH_USERS",
        "TWITTER_CUSTOM_SCHEDULE_TWEET",
    ]
