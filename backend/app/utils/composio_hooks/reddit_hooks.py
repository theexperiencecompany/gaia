"""
Reddit-specific hooks using the enhanced decorator system.

These hooks implement response processing for raw Reddit API data,
minimizing token usage by extracting only critical information.
"""

from typing import Any

from app.config.loggers import app_logger as logger
from composio.types import ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from .registry import register_after_hook, register_before_hook


def process_reddit_post(post_data: dict) -> dict:
    """
    Extract only critical information from a Reddit post.

    Args:
        post_data: Raw Reddit post data

    Returns:
        Minimized post data with only essential fields
    """
    try:
        data = post_data.get("data", {})

        return {
            "id": data.get("id", ""),
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "subreddit": data.get("subreddit", ""),
            "subreddit_name_prefixed": data.get("subreddit_name_prefixed", ""),
            "created_utc": data.get("created_utc", 0),
            "score": data.get("score", 0),
            "upvote_ratio": data.get("upvote_ratio", 0),
            "num_comments": data.get("num_comments", 0),
            "selftext": data.get("selftext", ""),
            "url": data.get("url", ""),
            "permalink": data.get("permalink", ""),
            "is_self": data.get("is_self", False),
            "link_flair_text": data.get("link_flair_text"),
            "over_18": data.get("over_18", False),
            "spoiler": data.get("spoiler", False),
            "locked": data.get("locked", False),
            "stickied": data.get("stickied", False),
        }
    except Exception as e:
        logger.error(f"Error processing Reddit post: {e}")
        return {}


def process_reddit_search_results(response_data: dict) -> dict:
    """
    Process Reddit search results to minimize data.

    Args:
        response_data: Raw Reddit API search response

    Returns:
        Processed search results with only critical information
    """
    try:
        search_results = response_data.get("search_results", {})
        data = search_results.get("data", {})
        children = data.get("children", [])

        # Process each post
        processed_posts = []
        for child in children:
            if child.get("kind") == "t3":  # t3 is a link/post
                processed_post = process_reddit_post(child)
                if processed_post:
                    processed_posts.append(processed_post)

        return {
            "posts": processed_posts,
            "after": data.get("after"),
            "before": data.get("before"),
            "result_count": len(processed_posts),
        }
    except Exception as e:
        logger.error(f"Error processing Reddit search results: {e}")
        return response_data


def process_reddit_comment(comment_data: dict) -> dict:
    """
    Extract only critical information from a Reddit comment.

    Args:
        comment_data: Raw Reddit comment data

    Returns:
        Minimized comment data with only essential fields
    """
    try:
        data = comment_data.get("data", {})

        return {
            "id": data.get("id", ""),
            "author": data.get("author", ""),
            "body": data.get("body", ""),
            "created_utc": data.get("created_utc", 0),
            "score": data.get("score", 0),
            "permalink": data.get("permalink", ""),
            "parent_id": data.get("parent_id", ""),
            "link_id": data.get("link_id", ""),
            "subreddit": data.get("subreddit", ""),
            "is_submitter": data.get("is_submitter", False),
            "stickied": data.get("stickied", False),
            "distinguished": data.get("distinguished"),
            "edited": data.get("edited", False),
        }
    except Exception as e:
        logger.error(f"Error processing Reddit comment: {e}")
        return {}


# ====================== BEFORE EXECUTE HOOKS ======================


@register_before_hook(
    tools=[
        "REDDIT_CREATE_REDDIT_POST",
        "REDDIT_POST_REDDIT_COMMENT",
        "REDDIT_EDIT_REDDIT_COMMENT_OR_POST",
    ]
)
def reddit_content_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle Reddit content creation/editing progress."""
    try:
        writer = get_stream_writer()
        if writer:
            arguments = params.get("arguments", {})

            if tool == "REDDIT_CREATE_REDDIT_POST":
                subreddit = arguments.get("subreddit", "")
                payload = {"progress": f"Creating post in r/{subreddit}..."}
            elif tool == "REDDIT_POST_REDDIT_COMMENT":
                payload = {"progress": "Posting comment..."}
            elif tool == "REDDIT_EDIT_REDDIT_COMMENT_OR_POST":
                payload = {"progress": "Editing content..."}
            else:
                return params

            writer(payload)
    except Exception as e:
        logger.error(f"Error in reddit_content_before_hook: {e}")

    return params


@register_before_hook(
    tools=["REDDIT_DELETE_REDDIT_POST", "REDDIT_DELETE_REDDIT_COMMENT"]
)
def reddit_delete_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle Reddit deletion progress."""
    try:
        writer = get_stream_writer()
        if writer:
            content_type = "post" if "POST" in tool else "comment"
            payload = {"progress": f"Deleting {content_type}..."}
            writer(payload)
    except Exception as e:
        logger.error(f"Error in reddit_delete_before_hook: {e}")

    return params


@register_before_hook(
    tools=["REDDIT_RETRIEVE_REDDIT_POST", "REDDIT_RETRIEVE_POST_COMMENTS"]
)
def reddit_retrieve_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle Reddit content retrieval progress."""
    try:
        writer = get_stream_writer()
        if writer:
            if tool == "REDDIT_RETRIEVE_REDDIT_POST":
                payload = {"progress": "Fetching post details..."}
            elif tool == "REDDIT_RETRIEVE_POST_COMMENTS":
                payload = {"progress": "Fetching post comments..."}
            else:
                return params

            writer(payload)
    except Exception as e:
        logger.error(f"Error in reddit_retrieve_before_hook: {e}")

    return params


# ====================== AFTER EXECUTE HOOKS ======================


@register_after_hook(tools=["REDDIT_SEARCH_ACROSS_SUBREDDITS"])
def reddit_search_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process Reddit search response to minimize raw data."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", {})

        # Process the raw search response
        processed_response = process_reddit_search_results(response["data"])

        if writer and processed_response.get("posts"):
            # Send search results to frontend
            reddit_search_data = []
            for post in processed_response["posts"]:
                reddit_search_data.append(
                    {
                        "id": post.get("id", ""),
                        "title": post.get("title", ""),
                        "author": post.get("author", ""),
                        "subreddit": post.get("subreddit_name_prefixed", ""),
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "created_utc": post.get("created_utc", 0),
                        "permalink": post.get("permalink", ""),
                        "url": post.get("url", ""),
                        "selftext": post.get("selftext", "")[:200] + "..."
                        if len(post.get("selftext", "")) > 200
                        else post.get("selftext", ""),
                    }
                )

            payload = {
                "reddit_data": {
                    "type": "search",
                    "posts": reddit_search_data,
                }
            }
            writer(payload)

        # Return processed response for LLM (minimal data)
        return processed_response

    except Exception as e:
        logger.error(f"Error in reddit_search_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(tools=["REDDIT_RETRIEVE_REDDIT_POST"])
def reddit_post_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process single Reddit post response and stream to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", {})

        # Get the post data (it's usually nested under 'data' in Reddit API)
        post_response = response.get("data", {})

        # Process the post
        processed_post = process_reddit_post(post_response)

        if writer and processed_post:
            # Send post data to frontend
            reddit_post_data = {
                "id": processed_post.get("id", ""),
                "title": processed_post.get("title", ""),
                "author": processed_post.get("author", ""),
                "subreddit": processed_post.get("subreddit_name_prefixed", ""),
                "score": processed_post.get("score", 0),
                "upvote_ratio": processed_post.get("upvote_ratio", 0),
                "num_comments": processed_post.get("num_comments", 0),
                "created_utc": processed_post.get("created_utc", 0),
                "selftext": processed_post.get("selftext", ""),
                "url": processed_post.get("url", ""),
                "permalink": processed_post.get("permalink", ""),
                "is_self": processed_post.get("is_self", False),
                "link_flair_text": processed_post.get("link_flair_text"),
            }

            payload = {
                "reddit_data": {
                    "type": "post",
                    "post": reddit_post_data,
                }
            }
            writer(payload)

        # Return processed response for LLM
        return processed_post

    except Exception as e:
        logger.error(f"Error in reddit_post_detail_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(tools=["REDDIT_RETRIEVE_POST_COMMENTS"])
def reddit_comments_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process Reddit comments response and stream to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", {})

        # Extract comments from Reddit API response
        response_data = response.get("data", {})

        # Reddit returns an array with [post_data, comments_data]
        comments_listing = []
        if isinstance(response_data, list) and len(response_data) > 1:
            comments_data = response_data[1].get("data", {}).get("children", [])
        else:
            # Alternative structure
            comments_data = (
                response_data.get("comments", {}).get("data", {}).get("children", [])
            )

        # Process comments
        processed_comments = []
        for comment_child in comments_data:
            if comment_child.get("kind") == "t1":  # t1 is a comment
                processed_comment = process_reddit_comment(comment_child)
                if processed_comment and processed_comment.get("body"):
                    processed_comments.append(processed_comment)

        if writer and processed_comments:
            # Transform to frontend format
            reddit_comment_data = []
            for comment in processed_comments[:50]:  # Limit to 50 comments for UI
                reddit_comment_data.append(
                    {
                        "id": comment.get("id", ""),
                        "author": comment.get("author", ""),
                        "body": comment.get("body", ""),
                        "score": comment.get("score", 0),
                        "created_utc": comment.get("created_utc", 0),
                        "permalink": comment.get("permalink", ""),
                        "is_submitter": comment.get("is_submitter", False),
                    }
                )

            payload = {
                "reddit_data": {
                    "type": "comments",
                    "comments": reddit_comment_data,
                }
            }
            writer(payload)

        # Return minimal data for LLM
        return {
            "comments": processed_comments,
            "comment_count": len(processed_comments),
        }

    except Exception as e:
        logger.error(f"Error in reddit_comments_after_hook: {e}")
        return response.get("data", {})


@register_after_hook(tools=["REDDIT_CREATE_REDDIT_POST", "REDDIT_POST_REDDIT_COMMENT"])
def reddit_content_created_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process Reddit content creation response and stream to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", {})

        response_data = response.get("data", {})

        if writer:
            if tool == "REDDIT_CREATE_REDDIT_POST":
                # Extract post info from response
                post_id = response_data.get("id", "")
                post_url = response_data.get("url", "")

                payload = {
                    "reddit_data": {
                        "type": "post_created",
                        "data": {
                            "id": post_id,
                            "url": post_url,
                            "message": "Post created successfully!",
                            "permalink": response_data.get("permalink", ""),
                        },
                    }
                }
                writer(payload)

            elif tool == "REDDIT_POST_REDDIT_COMMENT":
                # Extract comment info from response
                comment_id = response_data.get("id", "")

                payload = {
                    "reddit_data": {
                        "type": "comment_created",
                        "data": {
                            "id": comment_id,
                            "message": "Comment posted successfully!",
                            "permalink": response_data.get("permalink", ""),
                        },
                    }
                }
                writer(payload)

        # Return minimal response for LLM
        return {
            "id": response_data.get("id", ""),
            "success": True,
            "message": "Content created successfully",
        }

    except Exception as e:
        logger.error(f"Error in reddit_content_created_after_hook: {e}")
        return response.get("data", {})
