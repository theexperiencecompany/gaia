"""Twitter custom tools using Composio custom tool infrastructure.

Direct Twitter API v2 calls go through Composio's proxy via proxy_request_sync.
The proxy attaches OAuth server-side; tools only need user_id from auth_credentials.

Custom tools:
- CUSTOM_BATCH_FOLLOW: Follow multiple users at once
- CUSTOM_BATCH_UNFOLLOW: Unfollow multiple users at once
- CUSTOM_CREATE_THREAD: Create tweet threads in one call
- CUSTOM_SEARCH_USERS: Find users by name/bio when username unknown
- CUSTOM_SCHEDULE_TWEET: Schedule a tweet for later (draft)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from dataclasses import dataclass

from composio import Composio
from composio.types import ExecuteRequestFn
from langgraph.config import get_stream_writer

from app.constants.log_tags import LogTag
from app.decorators.documentation import with_doc
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.twitter import (
    TwitterTimelineResponse,
    TwitterUser,
    TwitterUserPublicMetrics,
    TwitterUserResponse,
)
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from app.templates.docstrings.twitter_tool_docs import (
    CUSTOM_BATCH_FOLLOW_DOC,
    CUSTOM_BATCH_UNFOLLOW_DOC,
    CUSTOM_CREATE_THREAD_DOC,
    CUSTOM_SCHEDULE_TWEET_DOC,
    CUSTOM_SEARCH_USERS_DOC,
)
from app.utils.twitter_utils import (
    TWITTER_API_BASE,
    TWITTER_TOOLKIT,
    create_tweet,
    follow_user,
    get_my_user_id,
    lookup_user_by_username,
    search_tweets,
    unfollow_user,
)
from shared.py.wide_events import log


def _user_id(auth_credentials: dict[str, object]) -> str:
    return CustomToolAuthCredentials.parse(auth_credentials).user_id


def _public_metrics(metrics: TwitterUserPublicMetrics | None) -> dict[str, object]:
    """A user's metrics for the stream; empty when X did not expand them."""
    # integer counts only: python and json dumps are identical
    return metrics.model_dump(mode="json") if metrics else {}  # pragma: no mutate


@dataclass(slots=True, frozen=True)
class _FollowTarget:
    """One account a batch follow/unfollow acts on; username is set when resolved from a handle."""

    user_id: str
    username: str | None = None


def _resolve_targets(
    user_id: str,
    request: BatchFollowInput | BatchUnfollowInput,
    results: list[dict[str, object]],
) -> tuple[list[_FollowTarget], int]:
    """Targets for the batch, appending a failed result per unknown handle; returns the failure count."""
    targets = [_FollowTarget(user_id=uid) for uid in request.user_ids or []]
    failed_count = 0
    for username in request.usernames or []:
        user_data = lookup_user_by_username(user_id, username)
        if user_data:
            targets.append(_FollowTarget(user_id=user_data.id, username=user_data.username))
        else:
            results.append({"username": username, "success": False, "error": "User not found"})
            failed_count += 1
    return targets, failed_count


def register_twitter_custom_tools(composio: Composio) -> list[str]:
    """Register Twitter custom tools with Composio."""

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_BATCH_FOLLOW_DOC)
    def CUSTOM_BATCH_FOLLOW(
        request: BatchFollowInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Follow multiple Twitter users at once."""
        del execute_request  # unused: framework-mandated custom-tool signature
        writer = get_stream_writer()
        user_id = _user_id(auth_credentials)

        my_user_id = get_my_user_id(user_id)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results: list[dict[str, object]] = []
        success_count = 0
        targets, failed_count = _resolve_targets(user_id, request, results)

        total = len(targets)
        if writer is not None:
            writer({"progress": f"Following {total} users..."})

        for i, target in enumerate(targets):
            result = follow_user(user_id, my_user_id, target.user_id)

            if result.success:
                results.append(
                    {"user_id": target.user_id, "username": target.username, "success": True}
                )
                success_count += 1
            else:
                results.append(
                    {
                        "user_id": target.user_id,
                        "username": target.username,
                        "success": False,
                        "error": result.error,
                    }
                )
                failed_count += 1

            if writer is not None and (i + 1) % 5 == 0:
                writer({"progress": f"Followed {i + 1}/{total} users..."})

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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Unfollow multiple Twitter users at once. DESTRUCTIVE - requires user consent."""
        del execute_request  # unused: framework-mandated custom-tool signature
        writer = get_stream_writer()
        user_id = _user_id(auth_credentials)

        my_user_id = get_my_user_id(user_id)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results: list[dict[str, object]] = []
        success_count = 0
        targets, failed_count = _resolve_targets(user_id, request, results)

        total = len(targets)
        if writer is not None:
            writer({"progress": f"Unfollowing {total} users..."})

        for i, target in enumerate(targets):
            result = unfollow_user(user_id, my_user_id, target.user_id)

            if result.success:
                results.append(
                    {"user_id": target.user_id, "username": target.username, "success": True}
                )
                success_count += 1
            else:
                results.append(
                    {
                        "user_id": target.user_id,
                        "username": target.username,
                        "success": False,
                        "error": result.error,
                    }
                )
                failed_count += 1

            if writer is not None and (i + 1) % 5 == 0:
                writer({"progress": f"Unfollowed {i + 1}/{total} users..."})

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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a Twitter thread (multiple connected tweets)."""
        del execute_request  # unused: framework-mandated custom-tool signature
        writer = get_stream_writer()
        user_id = _user_id(auth_credentials)

        if len(request.tweets) < 2:
            raise ValueError("Thread must have at least 2 tweets")

        tweet_ids: list[str] = []
        previous_tweet_id: str | None = None

        total_tweets = len(request.tweets)
        if writer is not None:
            writer({"progress": f"Creating thread with {total_tweets} tweets..."})

        for i, tweet_text in enumerate(request.tweets):
            media_ids = None
            if request.media_ids and i < len(request.media_ids):
                media_ids = request.media_ids[i] if request.media_ids[i] else None

            result = create_tweet(
                user_id,
                tweet_text,
                reply_to_tweet_id=previous_tweet_id,
                media_ids=media_ids,
            )

            if not result.success or result.tweet is None:  # pragma: no mutate — set iff success
                raise RuntimeError(
                    f"Failed at tweet {i + 1}: {result.error}. Partial tweet IDs: {tweet_ids}"
                )

            tweet_id = result.tweet.id
            tweet_ids.append(tweet_id)
            previous_tweet_id = tweet_id

            if writer is not None:
                writer({"progress": f"Posted tweet {i + 1}/{total_tweets}..."})

        try:
            username = TwitterUserResponse.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=TWITTER_TOOLKIT,
                        endpoint=f"{TWITTER_API_BASE}/users/me",
                        method="GET",
                    )
                )
            ).data.username
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Search for Twitter users by name, bio, or keywords."""
        del execute_request  # unused: framework-mandated custom-tool signature
        writer = get_stream_writer()
        user_id = _user_id(auth_credentials)

        if writer is not None:
            writer({"progress": f"Searching for users matching: {request.query}..."})

        search_query = f"{request.query} -is:retweet"
        result = search_tweets(user_id, search_query, max_results=request.max_results * 3)

        if not result.success or result.data is None:  # pragma: no mutate — data set iff success
            raise RuntimeError(f"Search failed: {result.error}")

        users_map: dict[str, TwitterUser] = {}
        for user in result.data.includes.users:
            if user.id not in users_map:
                users_map[user.id] = user

        unique_users = list(users_map.values())[: request.max_results]

        if writer is not None and unique_users:
            writer(
                {
                    "twitter_user_data": [
                        {
                            "id": u.id,
                            "username": u.username,
                            "name": u.name,
                            "description": u.description or "",
                            "profile_image_url": u.profile_image_url,
                            "verified": u.verified or False,
                            "public_metrics": _public_metrics(u.public_metrics),
                            "created_at": u.created_at,
                            "location": u.location,
                        }
                        for u in unique_users
                    ]
                }
            )

        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": u.name,
                    "description": (u.description or "")[:150],
                    "followers": u.public_metrics.followers_count if u.public_metrics else 0,
                    "verified": u.verified or False,
                }
                for u in unique_users
            ],
            "count": len(unique_users),
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    @with_doc(CUSTOM_SCHEDULE_TWEET_DOC)
    def CUSTOM_SCHEDULE_TWEET(
        request: ScheduleTweetInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Schedule a tweet for later posting (creates a draft with scheduled time).

        Note: Twitter API doesn't support scheduled tweets directly for free tier.
        This creates a draft that can be stored and posted later by a scheduler.
        """
        del execute_request  # unused: framework-mandated custom-tool signature
        writer = get_stream_writer()
        _user_id(auth_credentials)

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
            "message": (
                f"Tweet scheduled for {request.scheduled_time}. "
                "Note: Actual scheduling requires a backend scheduler service."
            ),
        }

    @composio.tools.custom_tool(toolkit="TWITTER")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Twitter/X context snapshot: profile info and recent tweets.

        Zero required parameters. Returns authenticated user's profile and recent activity.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)

        me = TwitterUserResponse.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=TWITTER_TOOLKIT,
                    endpoint=f"{TWITTER_API_BASE}/users/me",
                    method="GET",
                    query={"user.fields": "public_metrics,description,username"},
                )
            )
        ).data
        metrics = me.public_metrics

        tweets: list[dict[str, object]] = []
        try:
            timeline = TwitterTimelineResponse.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=TWITTER_TOOLKIT,
                        endpoint=f"{TWITTER_API_BASE}/users/{me.id}/tweets",
                        method="GET",
                        query={
                            "max_results": 5,
                            "tweet.fields": "created_at,public_metrics",
                        },
                    )
                )
            )
            tweets = [
                {
                    "id": t.id,
                    "text": t.text[:200],
                    "created_at": t.created_at,
                    "likes": t.public_metrics.like_count if t.public_metrics else 0,
                    "retweets": t.public_metrics.retweet_count if t.public_metrics else 0,
                }
                for t in timeline.data
            ]
        except Exception as e:
            # Profile context is still useful without recent tweets, so this
            # returns a partial result rather than failing the whole tool.
            log.warning(
                f"{LogTag.TOOL} Failed to fetch recent tweets, returning profile without them",
                twitter_user_id=me.id,
                error=str(e),
                error_type=type(e).__name__,
            )

        return {
            "user": {
                "id": me.id,
                "username": me.username,
                "name": me.name,
                "description": (me.description or "")[:200],
                "followers": metrics.followers_count if metrics else 0,
                "following": metrics.following_count if metrics else 0,
                "tweet_count": metrics.tweet_count if metrics else 0,
            },
            "recent_tweets": tweets,
        }

    return [
        "TWITTER_CUSTOM_BATCH_FOLLOW",
        "TWITTER_CUSTOM_BATCH_UNFOLLOW",
        "TWITTER_CUSTOM_CREATE_THREAD",
        "TWITTER_CUSTOM_SEARCH_USERS",
        "TWITTER_CUSTOM_SCHEDULE_TWEET",
        "TWITTER_CUSTOM_GATHER_CONTEXT",
    ]
