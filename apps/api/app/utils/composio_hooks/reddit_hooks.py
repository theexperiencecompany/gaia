"""
Reddit-specific hooks using the enhanced decorator system.

These hooks implement response processing for raw Reddit API data,
minimizing token usage by extracting only critical information.
"""

from typing import TypedDict

from composio.types import ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from app.constants.log_tags import LogTag
from app.models.integrations.composio_hooks import ComposioToolCall, ComposioToolResponse
from app.models.integrations.reddit_hooks import (
    RedditComment,
    RedditCommentListing,
    RedditCommentsData,
    RedditCreatedContent,
    RedditCreatePostArguments,
    RedditPost,
    RedditPostDetail,
    RedditSearchData,
)
from shared.py.wide_events import log

from .registry import AfterHookResponse, register_after_hook, register_before_hook

# Reddit's ``kind`` prefixes: a link (post) and a comment.
_POST_KIND = "t3"
_COMMENT_KIND = "t1"
_UI_COMMENT_LIMIT = 50
_UI_SELFTEXT_LIMIT = 200


class RedditPostSummary(TypedDict):
    """A post trimmed to what the LLM needs."""

    id: str
    title: str
    author: str
    subreddit: str
    subreddit_name_prefixed: str
    created_utc: int | float
    score: int
    upvote_ratio: int | float
    num_comments: int
    selftext: str
    url: str
    permalink: str
    is_self: bool
    link_flair_text: str | None
    over_18: bool
    spoiler: bool
    locked: bool
    stickied: bool


class RedditSearchSummary(TypedDict):
    posts: list[RedditPostSummary]
    after: str | None
    before: str | None
    result_count: int


class RedditCommentSummary(TypedDict):
    """A comment trimmed to what the LLM needs."""

    id: str
    author: str
    body: str
    created_utc: int | float
    score: int
    permalink: str
    parent_id: str
    link_id: str
    subreddit: str
    is_submitter: bool
    stickied: bool
    distinguished: str | None
    edited: bool | int | float


class RedditCommentsSummary(TypedDict):
    comments: list[RedditCommentSummary]
    comment_count: int


class RedditContentCreatedSummary(TypedDict):
    id: str | None
    success: bool
    message: str


def process_reddit_post(post: RedditPost) -> RedditPostSummary:
    """Extract only critical information from a Reddit post (a t3 thing's data)."""
    return {
        "id": post.id,
        "title": post.title,
        "author": post.author,
        "subreddit": post.subreddit,
        "subreddit_name_prefixed": post.subreddit_name_prefixed,
        "created_utc": post.created_utc,
        "score": post.score,
        "upvote_ratio": post.upvote_ratio,
        "num_comments": post.num_comments,
        "selftext": post.selftext,
        "url": post.url,
        "permalink": post.permalink,
        "is_self": post.is_self,
        "link_flair_text": post.link_flair_text,
        "over_18": post.over_18,
        "spoiler": post.spoiler,
        "locked": post.locked,
        "stickied": post.stickied,
    }


def process_reddit_search_results(data: RedditSearchData) -> RedditSearchSummary:
    """Process Reddit search results to minimize data: the t3 posts and the page cursors."""
    listing = data.search_results.data
    processed_posts = [
        process_reddit_post(child.data) for child in listing.children if child.kind == _POST_KIND
    ]

    return {
        "posts": processed_posts,
        "after": listing.after,
        "before": listing.before,
        "result_count": len(processed_posts),
    }


def process_reddit_comment(comment: RedditComment) -> RedditCommentSummary:
    """Extract only critical information from a Reddit comment (a t1 thing's data)."""
    return {
        "id": comment.id,
        "author": comment.author,
        "body": comment.body,
        "created_utc": comment.created_utc,
        "score": comment.score,
        "permalink": comment.permalink,
        "parent_id": comment.parent_id,
        "link_id": comment.link_id,
        "subreddit": comment.subreddit,
        "is_submitter": comment.is_submitter,
        "stickied": comment.stickied,
        "distinguished": comment.distinguished,
        "edited": comment.edited,
    }


def _ui_selftext(post: RedditPost) -> str:
    return (
        post.selftext[:_UI_SELFTEXT_LIMIT] + "..."
        if len(post.selftext) > _UI_SELFTEXT_LIMIT
        else post.selftext
    )


def _comment_listing(raw: object) -> RedditCommentListing:
    """Return the comments listing from either shape REDDIT_RETRIEVE_POST_COMMENTS answers.

    Composio types data as a dict, but Reddit's raw listing API for this endpoint
    returns a top-level array [post_listing, comments_listing] — either shape can arrive.
    """
    if isinstance(raw, list):
        if len(raw) > 1 and isinstance(raw[1], dict):
            return RedditCommentListing.model_validate(raw[1])
        return RedditCommentListing()
    return RedditCommentsData.model_validate(raw).comments


def _ui_comment(comment: RedditComment) -> dict[str, object]:
    return {
        "id": comment.id,
        "author": comment.author,
        "body": comment.body,
        "score": comment.score,
        "created_utc": comment.created_utc,
        "permalink": comment.permalink,
        "is_submitter": comment.is_submitter,
    }


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
        if writer is not None:
            if tool == "REDDIT_CREATE_REDDIT_POST":
                arguments = RedditCreatePostArguments.model_validate(
                    ComposioToolCall.model_validate(params).arguments
                )
                payload = {"progress": f"Creating post in r/{arguments.subreddit}..."}
            elif tool == "REDDIT_POST_REDDIT_COMMENT":
                payload = {"progress": "Posting comment..."}
            elif tool == "REDDIT_EDIT_REDDIT_COMMENT_OR_POST":
                payload = {"progress": "Editing content..."}
            else:
                return params

            writer(payload)
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_content_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["REDDIT_DELETE_REDDIT_POST", "REDDIT_DELETE_REDDIT_COMMENT"])
def reddit_delete_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle Reddit deletion progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            content_type = "post" if "POST" in tool else "comment"
            payload = {"progress": f"Deleting {content_type}..."}
            writer(payload)
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_delete_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["REDDIT_RETRIEVE_REDDIT_POST", "REDDIT_RETRIEVE_POST_COMMENTS"])
def reddit_retrieve_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle Reddit content retrieval progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            if tool == "REDDIT_RETRIEVE_REDDIT_POST":
                payload = {"progress": "Fetching post details..."}
            elif tool == "REDDIT_RETRIEVE_POST_COMMENTS":
                payload = {"progress": "Fetching post comments..."}
            else:
                return params

            writer(payload)
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_retrieve_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


# ====================== AFTER EXECUTE HOOKS ======================


@register_after_hook(tools=["REDDIT_SEARCH_ACROSS_SUBREDDITS"])
def reddit_search_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process Reddit search response to minimize raw data."""
    log.set(reddit_tool=tool, toolkit=toolkit)
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        # Process the raw search response
        data = RedditSearchData.model_validate(raw)
        processed_response = process_reddit_search_results(data)
        posts = [
            child.data for child in data.search_results.data.children if child.kind == _POST_KIND
        ]

        if writer is not None and posts:
            # Send search results to frontend
            reddit_search_data = [
                {
                    "id": post.id,
                    "title": post.title,
                    "author": post.author,
                    "subreddit": post.subreddit_name_prefixed,
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "created_utc": post.created_utc,
                    "permalink": post.permalink,
                    "url": post.url,
                    "selftext": _ui_selftext(post),
                }
                for post in posts
            ]

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
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_search_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["REDDIT_RETRIEVE_REDDIT_POST"])
def reddit_post_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process single Reddit post response and stream to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        # The post is nested under 'data', as a Reddit thing
        post = RedditPostDetail.model_validate(raw).data

        if writer is not None:
            # Send post data to frontend
            reddit_post_data = {
                "id": post.id,
                "title": post.title,
                "author": post.author,
                "subreddit": post.subreddit_name_prefixed,
                "score": post.score,
                "upvote_ratio": post.upvote_ratio,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "selftext": post.selftext,
                "url": post.url,
                "permalink": post.permalink,
                "is_self": post.is_self,
                "link_flair_text": post.link_flair_text,
            }

            payload = {
                "reddit_data": {
                    "type": "post",
                    "post": reddit_post_data,
                }
            }
            writer(payload)

        # Return processed response for LLM
        return process_reddit_post(post)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_post_detail_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["REDDIT_RETRIEVE_POST_COMMENTS"])
def reddit_comments_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process Reddit comments response and stream to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        listing = _comment_listing(raw)

        # Process comments: the ``t1`` things that carry a body
        comment_things = [
            child
            for child in listing.data.children
            if child.kind == _COMMENT_KIND and child.data.body
        ]
        processed_comments = [process_reddit_comment(child.data) for child in comment_things]

        if writer is not None and processed_comments:
            # Transform to frontend format, limited for the UI
            reddit_comment_data = [
                _ui_comment(child.data) for child in comment_things[:_UI_COMMENT_LIMIT]
            ]

            payload = {
                "reddit_data": {
                    "type": "comments",
                    "comments": reddit_comment_data,
                }
            }
            writer(payload)

        # Return minimal data for LLM
        summary: RedditCommentsSummary = {
            "comments": processed_comments,
            "comment_count": len(processed_comments),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_comments_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["REDDIT_CREATE_REDDIT_POST", "REDDIT_POST_REDDIT_COMMENT"])
def reddit_content_created_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process Reddit content creation response and stream to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if isinstance(raw, dict) and "error" in raw:
            return raw

        created = RedditCreatedContent.model_validate(raw)

        if writer is not None:
            if tool == "REDDIT_CREATE_REDDIT_POST":
                payload = {
                    "reddit_data": {
                        "type": "post_created",
                        "data": {
                            "id": created.id,
                            "url": created.url,
                            "message": "Post created successfully!",
                            "permalink": created.permalink,
                        },
                    }
                }
                writer(payload)

            elif tool == "REDDIT_POST_REDDIT_COMMENT":
                payload = {
                    "reddit_data": {
                        "type": "comment_created",
                        "data": {
                            "id": created.id,
                            "message": "Comment posted successfully!",
                            "permalink": created.permalink,
                        },
                    }
                }
                writer(payload)

        # Return minimal response for LLM
        summary: RedditContentCreatedSummary = {
            "id": created.id,
            "success": True,
            "message": "Content created successfully",
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in reddit_content_created_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw
