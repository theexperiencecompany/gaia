"""
Twitter-specific hooks using the enhanced decorator system.

These hooks implement schema modifiers for customizing tool descriptions,
before/after hooks for data processing, and frontend streaming via writer.
"""

from typing import Any

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from app.config.loggers import app_logger as logger

from .registry import (
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
)


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
    """
    Add guidance to search for user first if username is unknown.
    """
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
    """
    Add guidance for creating tweets with media and threads.
    """
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
    """
    Set sensible defaults for timeline requests.
    """
    props = schema.input_parameters.get("properties", {})

    if "max_results" in props:
        props["max_results"]["default"] = 20

    return schema


@register_before_hook(tools=["TWITTER_CREATION_OF_A_POST"])
def twitter_create_post_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Stream post creation data to frontend for preview."""
    try:
        writer = get_stream_writer()
        if not writer:  # type: ignore[truthy-function]
            return params

        arguments = params.get("arguments", {})

        # Build post preview data for frontend
        post_data = {
            "text": arguments.get("text", ""),
            "quote_tweet_id": arguments.get("quote_tweet_id"),
            "reply_to_tweet_id": arguments.get("reply_in_reply_to_tweet_id"),
            "media_ids": arguments.get("media_media_ids", []),
            "poll_options": arguments.get("poll_options", []),
        }

        payload = {
            "twitter_post_preview": post_data,
        }
        writer(payload)

    except Exception as e:
        logger.error(f"Error in twitter_create_post_before_hook: {e}")

    return params


@register_before_hook(tools=["TWITTER_RECENT_SEARCH", "TWITTER_FULL_ARCHIVE_SEARCH"])
def twitter_search_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Send search progress to frontend."""
    try:
        writer = get_stream_writer()
        if not writer:  # type: ignore[truthy-function]
            return params

        arguments = params.get("arguments", {})
        query = arguments.get("query", "")

        payload = {"progress": f"Searching tweets for: {query}..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in twitter_search_before_hook: {e}")

    return params


@register_after_hook(tools=["TWITTER_RECENT_SEARCH", "TWITTER_FULL_ARCHIVE_SEARCH"])
def twitter_search_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process search response and send tweet data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response["data"]

        data = response.get("data", {})
        tweets = data.get("data", [])
        includes = data.get("includes", {})
        users_map = {}

        # Build user lookup map
        for user in includes.get("users", []):
            users_map[user.get("id")] = {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "profile_image_url": user.get("profile_image_url"),
                "verified": user.get("verified", False),
                "description": user.get("description", ""),
                "public_metrics": user.get("public_metrics", {}),
            }

        # Process tweets for frontend display
        processed_tweets = []
        for tweet in tweets:
            author_id = tweet.get("author_id")
            author = users_map.get(
                author_id, {"username": "unknown", "name": "Unknown"}
            )

            processed_tweet = {
                "id": tweet.get("id"),
                "text": tweet.get("text"),
                "created_at": tweet.get("created_at"),
                "author": author,
                "public_metrics": tweet.get("public_metrics", {}),
                "conversation_id": tweet.get("conversation_id"),
            }
            processed_tweets.append(processed_tweet)

        # Send to frontend
        if writer is not None and processed_tweets:
            payload = {
                "twitter_search_data": {
                    "tweets": processed_tweets,
                    "result_count": data.get("meta", {}).get(
                        "result_count", len(processed_tweets)
                    ),
                    "next_token": data.get("meta", {}).get("next_token"),
                },
            }
            writer(payload)

        # Return cleaned data for LLM (minimize tokens)
        llm_tweets = []
        for tweet in processed_tweets[:10]:  # Limit to 10 for LLM context
            llm_tweets.append(
                {
                    "id": tweet["id"],
                    "text": tweet["text"][:200] + "..."
                    if len(tweet["text"]) > 200
                    else tweet["text"],
                    "author_username": tweet["author"].get("username"),
                    "author_name": tweet["author"].get("name"),
                    "likes": tweet["public_metrics"].get("like_count", 0),
                    "retweets": tweet["public_metrics"].get("retweet_count", 0),
                }
            )

        return {
            "tweets": llm_tweets,
            "result_count": data.get("meta", {}).get(
                "result_count", len(processed_tweets)
            ),
            "has_more": bool(data.get("meta", {}).get("next_token")),
        }

    except Exception as e:
        logger.error(f"Error in twitter_search_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(
    tools=["TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER_USER_LOOKUP_BY_USERNAMES"]
)
def twitter_user_lookup_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process user lookup and stream profile data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response["data"]

        data = response.get("data", {})
        user_data = data.get("data", data)

        # Handle both single user and multiple users
        users = (
            user_data
            if isinstance(user_data, list)
            else [user_data]
            if user_data
            else []
        )

        processed_users = []
        for user in users:
            processed_user = {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "description": user.get("description", ""),
                "profile_image_url": user.get("profile_image_url"),
                "verified": user.get("verified", False),
                "public_metrics": user.get("public_metrics", {}),
                "created_at": user.get("created_at"),
                "location": user.get("location"),
                "url": user.get("url"),
            }
            processed_users.append(processed_user)

        # Send to frontend
        if writer is not None and processed_users:
            payload = {
                "twitter_user_data": processed_users,
            }
            writer(payload)

        # Return for LLM
        return {
            "users": [
                {
                    "id": u["id"],
                    "username": u["username"],
                    "name": u["name"],
                    "followers": u["public_metrics"].get("followers_count", 0),
                    "following": u["public_metrics"].get("following_count", 0),
                    "verified": u["verified"],
                }
                for u in processed_users
            ]
        }

    except Exception as e:
        logger.error(f"Error in twitter_user_lookup_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(tools=["TWITTER_USER_HOME_TIMELINE_BY_USER_ID"])
def twitter_timeline_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process timeline and stream tweets to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response["data"]

        data = response.get("data", {})
        tweets = data.get("data", [])
        includes = data.get("includes", {})
        users_map = {}

        # Build user lookup map
        for user in includes.get("users", []):
            users_map[user.get("id")] = {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "profile_image_url": user.get("profile_image_url"),
                "verified": user.get("verified", False),
            }

        # Process tweets
        processed_tweets = []
        for tweet in tweets:
            author_id = tweet.get("author_id")
            author = users_map.get(
                author_id, {"username": "unknown", "name": "Unknown"}
            )

            processed_tweets.append(
                {
                    "id": tweet.get("id"),
                    "text": tweet.get("text"),
                    "created_at": tweet.get("created_at"),
                    "author": author,
                    "public_metrics": tweet.get("public_metrics", {}),
                }
            )

        # Send to frontend
        if writer is not None and processed_tweets:
            payload = {
                "twitter_timeline_data": {
                    "tweets": processed_tweets,
                }
            }
            writer(payload)

        # Return cleaned for LLM
        return {
            "tweets": [
                {
                    "id": t["id"],
                    "text": t["text"][:200] + "..."
                    if len(t["text"]) > 200
                    else t["text"],
                    "author": t["author"].get("username"),
                    "likes": t["public_metrics"].get("like_count", 0),
                }
                for t in processed_tweets[:10]
            ],
            "count": len(processed_tweets),
        }

    except Exception as e:
        logger.error(f"Error in twitter_timeline_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(
    tools=["TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER_FOLLOWING_BY_USER_ID"]
)
def twitter_followers_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process followers/following list and stream to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response["data"]

        data = response.get("data", {})
        users = data.get("data", [])

        processed_users = []
        for user in users:
            processed_users.append(
                {
                    "id": user.get("id"),
                    "username": user.get("username"),
                    "name": user.get("name"),
                    "profile_image_url": user.get("profile_image_url"),
                    "verified": user.get("verified", False),
                    "description": user.get("description", ""),
                    "public_metrics": user.get("public_metrics", {}),
                }
            )

        # Send to frontend
        if writer is not None and processed_users:
            action = "followers" if "FOLLOWERS" in tool else "following"
            payload = {
                f"twitter_{action}_data": processed_users,
            }
            writer(payload)

        # Return for LLM
        return {
            "users": [
                {
                    "id": u["id"],
                    "username": u["username"],
                    "name": u["name"],
                    "followers": u["public_metrics"].get("followers_count", 0),
                }
                for u in processed_users[:20]
            ],
            "count": len(processed_users),
            "has_more": bool(data.get("meta", {}).get("next_token")),
        }

    except Exception as e:
        logger.error(f"Error in twitter_followers_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(tools=["TWITTER_CREATION_OF_A_POST"])
def twitter_post_created_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Send created post data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response["data"]

        data = response.get("data", {})
        post_data = data.get("data", {})

        if writer is not None and post_data:
            payload = {
                "twitter_post_created": {
                    "id": post_data.get("id"),
                    "text": post_data.get("text"),
                    "url": f"https://twitter.com/i/status/{post_data.get('id')}",
                },
            }
            writer(payload)

        return {
            "success": True,
            "id": post_data.get("id"),
            "text": post_data.get("text"),
            "url": f"https://twitter.com/i/status/{post_data.get('id')}",
        }

    except Exception as e:
        logger.error(f"Error in twitter_post_created_after_hook: {e}")
        return response.get("data", {})
