"""Unit tests for the Reddit Composio hooks (``reddit_hooks``).

Hermetic tests for ``app.utils.composio_hooks.reddit_hooks``: the three pure
processors (post / search-results / comment extraction) pin the exact returned
dicts, defaults, and error paths; the before/after hooks mock the
``get_stream_writer`` and ``log`` seams and assert the exact streamed payloads,
the exact LLM-facing return values, and the exact error logs. All external
I/O (stream writer, logging) is mocked; nothing touches the network.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from composio.types import ToolExecuteParams

from app.utils.composio_hooks.reddit_hooks import (
    process_reddit_comment,
    process_reddit_post,
    process_reddit_search_results,
    reddit_comments_after_hook,
    reddit_content_before_hook,
    reddit_content_created_after_hook,
    reddit_delete_before_hook,
    reddit_post_detail_after_hook,
    reddit_retrieve_before_hook,
    reddit_search_after_hook,
)


def _make_params(arguments: dict | None = None, **extra: Any) -> ToolExecuteParams:
    """Create a ToolExecuteParams-like dict."""
    params: dict[str, Any] = {"arguments": arguments or {}}
    params.update(extra)
    return params  # type: ignore[return-value]


def _make_response(
    data: dict[str, Any] | list[Any], successful: bool = True, error: str | None = None
) -> dict[str, Any]:
    """Create a ToolExecutionResponse-like dict."""
    resp: dict[str, Any] = {"data": data, "successful": successful}
    if error is not None:
        resp["error"] = error
    return resp


def _noop_writer() -> MagicMock:
    """Return a callable mock suitable for ``get_stream_writer``."""
    return MagicMock()


def _assert_logged_error(
    mock_log: MagicMock, message: str, error: str, error_type: str
) -> None:
    """Assert the exact message, error string and error_type of a log.error call."""
    mock_log.error.assert_called_once()
    assert message in mock_log.error.call_args.args[0]
    assert mock_log.error.call_args.kwargs["error"] == error
    assert mock_log.error.call_args.kwargs["error_type"] == error_type


_REDDIT_POST_DEFAULTS: dict[str, Any] = {
    "id": "",
    "title": "",
    "author": "",
    "subreddit": "",
    "subreddit_name_prefixed": "",
    "created_utc": 0,
    "score": 0,
    "upvote_ratio": 0,
    "num_comments": 0,
    "selftext": "",
    "url": "",
    "permalink": "",
    "is_self": False,
    "link_flair_text": None,
    "over_18": False,
    "spoiler": False,
    "locked": False,
    "stickied": False,
}

_REDDIT_COMMENT_DEFAULTS: dict[str, Any] = {
    "id": "",
    "author": "",
    "body": "",
    "created_utc": 0,
    "score": 0,
    "permalink": "",
    "parent_id": "",
    "link_id": "",
    "subreddit": "",
    "is_submitter": False,
    "stickied": False,
    "distinguished": None,
    "edited": False,
}


def _make_reddit_post_data(**overrides: Any) -> dict[str, Any]:
    """Full Reddit post ``data`` dict (every field present, truthy flags)."""
    post = {
        "id": "abc123",
        "title": "Test Post",
        "author": "testuser",
        "subreddit": "python",
        "subreddit_name_prefixed": "r/python",
        "created_utc": 1704067200,
        "score": 42,
        "upvote_ratio": 0.95,
        "num_comments": 10,
        "selftext": "Hello world",
        "url": "https://reddit.com/r/python/abc",
        "permalink": "/r/python/comments/abc",
        "is_self": True,
        "link_flair_text": "Discussion",
        "over_18": True,
        "spoiler": True,
        "locked": True,
        "stickied": True,
    }
    post.update(overrides)
    return post


def _make_reddit_comment_data(**overrides: Any) -> dict[str, Any]:
    """Full Reddit comment ``data`` dict (every field present, truthy flags)."""
    comment = {
        "id": "cmt1",
        "author": "commenter",
        "body": "Great post!",
        "created_utc": 1704067200,
        "score": 15,
        "permalink": "/r/python/comments/abc/cmt1",
        "parent_id": "t3_abc",
        "link_id": "t3_abc",
        "subreddit": "python",
        "is_submitter": True,
        "stickied": True,
        "distinguished": "moderator",
        "edited": True,
    }
    comment.update(overrides)
    return comment
class TestRedditHelpers:
    """Tests for Reddit helper functions (process_reddit_post, etc.)."""

    def test_process_reddit_post_extracts_fields(self) -> None:
        post_data = _make_reddit_post_data()
        result = process_reddit_post({"data": post_data})
        assert result == post_data

    def test_process_reddit_post_empty_data_uses_defaults(self) -> None:
        result = process_reddit_post({})
        assert result == _REDDIT_POST_DEFAULTS

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_post_non_dict_data_logs_and_returns_empty(
        self, mock_log: MagicMock
    ) -> None:
        result = process_reddit_post({"data": "not a dict"})
        assert result == {}
        _assert_logged_error(
            mock_log,
            "Error processing Reddit post",
            "'str' object has no attribute 'get'",
            "AttributeError",
        )

    def test_process_reddit_comment_extracts_fields(self) -> None:
        comment_data = _make_reddit_comment_data()
        result = process_reddit_comment({"data": comment_data})
        assert result == comment_data

    def test_process_reddit_comment_empty_data_uses_defaults(self) -> None:
        result = process_reddit_comment({})
        assert result == _REDDIT_COMMENT_DEFAULTS

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_comment_non_dict_data_logs_and_returns_empty(
        self, mock_log: MagicMock
    ) -> None:
        result = process_reddit_comment({"data": 123})
        assert result == {}
        _assert_logged_error(
            mock_log,
            "Error processing Reddit comment",
            "'int' object has no attribute 'get'",
            "AttributeError",
        )

    def test_process_reddit_search_results_extracts_posts(self) -> None:
        post_data = _make_reddit_post_data(id="p1", title="Post 1")
        response = {
            "search_results": {
                "data": {
                    "children": [
                        {"kind": "t3", "data": post_data},
                        {"kind": "t1", "data": _make_reddit_comment_data()},
                        {"kind": "more", "data": {"id": "more1"}},
                    ],
                    "after": "cursor123",
                    "before": "prev_123",
                }
            }
        }
        result = process_reddit_search_results(response)
        assert result == {
            "posts": [post_data],
            "after": "cursor123",
            "before": "prev_123",
            "result_count": 1,
        }

    def test_process_reddit_search_results_missing_keys_use_defaults(self) -> None:
        result = process_reddit_search_results({})
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}

    def test_process_reddit_search_results_empty_children(self) -> None:
        result = process_reddit_search_results({"search_results": {"data": {"children": []}}})
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_search_results_skips_t3_with_invalid_data(
        self, mock_log: MagicMock
    ) -> None:
        response = {
            "search_results": {
                "data": {"children": [{"kind": "t3", "data": "not a dict"}]}
            }
        }
        result = process_reddit_search_results(response)
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_search_results_non_dict_search_results_returns_original(
        self, mock_log: MagicMock
    ) -> None:
        response: dict[str, Any] = {"search_results": "not a dict"}
        result = process_reddit_search_results(response)
        assert result is response
        _assert_logged_error(
            mock_log,
            "Error processing Reddit search results",
            "'str' object has no attribute 'get'",
            "AttributeError",
        )


class TestRedditBeforeHooks:
    """Tests for Reddit before-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"subreddit": "python"})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Creating post in r/python..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post_without_subreddit(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Creating post in r/..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post_without_arguments_key(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"custom_key": "x"}
        reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Creating post in r/..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_post_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_POST_REDDIT_COMMENT", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Posting comment..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_edit(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_EDIT_REDDIT_COMMENT_OR_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Editing content..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_before_hook_unknown_tool_does_not_write(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_content_before_hook("REDDIT_OTHER_TOOL", "REDDIT", params)
        assert result is params
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting post..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_COMMENT", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting comment..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching post details..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_comments(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching post comments..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_retrieve_before_hook_unknown_tool_does_not_write(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_OTHER_TOOL", "REDDIT", params)
        assert result is params
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params


class TestRedditAfterHooks:
    """Tests for Reddit after-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_sets_log_context(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response = _make_response({"search_results": {"data": {"children": []}}})
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        mock_log.set.assert_called_once_with(
            reddit_tool="REDDIT_SEARCH_ACROSS_SUBREDDITS", toolkit="REDDIT"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_processes_results(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(
            id="p1",
            title="Python Tips",
            author="dev",
            permalink="/r/python/p1",
            url="https://reddit.com/r/python/p1",
            selftext="Short text",
        )
        response = _make_response(
            {
                "search_results": {
                    "data": {
                        "children": [{"kind": "t3", "data": post_data}],
                        "after": "cur123",
                        "before": None,
                    }
                }
            }
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {
            "posts": [post_data],
            "after": "cur123",
            "before": None,
            "result_count": 1,
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "search",
                    "posts": [
                        {
                            "id": "p1",
                            "title": "Python Tips",
                            "author": "dev",
                            "subreddit": "r/python",
                            "score": 42,
                            "num_comments": 10,
                            "created_utc": 1704067200,
                            "permalink": "/r/python/p1",
                            "url": "https://reddit.com/r/python/p1",
                            "selftext": "Short text",
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_truncates_long_selftext(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        long_text = "x" * 250
        post_data = _make_reddit_post_data(id="p1", selftext=long_text)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result["posts"][0]["selftext"] == long_text
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_selftext_at_200_chars_is_not_truncated(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        exact_text = "x" * 200
        post_data = _make_reddit_post_data(id="p1", selftext=exact_text)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == exact_text

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_selftext_at_201_chars_is_truncated(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(id="p1", selftext="x" * 201)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": {}}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {
            "posts": [_REDDIT_POST_DEFAULTS],
            "after": None,
            "before": None,
            "result_count": 1,
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "search",
                    "posts": [
                        {
                            "id": "",
                            "title": "",
                            "author": "",
                            "subreddit": "",
                            "score": 0,
                            "num_comments": 0,
                            "created_utc": 0,
                            "permalink": "",
                            "url": "",
                            "selftext": "",
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_no_posts_does_not_stream(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t1", "data": {"id": "c1"}}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_no_writer_returns_processed(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        post_data = _make_reddit_post_data()
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"posts": [post_data], "after": None, "before": None, "result_count": 1}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Rate limited"})
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"error": "Rate limited"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_empty_response_returns_empty_without_error_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_missing_data_key_logs_and_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(id="p1", title="Detail Post")
        response = _make_response({"data": post_data})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == post_data
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post",
                    "post": {
                        "id": "p1",
                        "title": "Detail Post",
                        "author": "testuser",
                        "subreddit": "r/python",
                        "score": 42,
                        "upvote_ratio": 0.95,
                        "num_comments": 10,
                        "created_utc": 1704067200,
                        "selftext": "Hello world",
                        "url": "https://reddit.com/r/python/abc",
                        "permalink": "/r/python/comments/abc",
                        "is_self": True,
                        "link_flair_text": "Discussion",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        post_data = _make_reddit_post_data()
        response = _make_response({"data": post_data})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == post_data

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": {}})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == _REDDIT_POST_DEFAULTS
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post",
                    "post": {
                        "id": "",
                        "title": "",
                        "author": "",
                        "subreddit": "",
                        "score": 0,
                        "upvote_ratio": 0,
                        "num_comments": 0,
                        "created_utc": 0,
                        "selftext": "",
                        "url": "",
                        "permalink": "",
                        "is_self": False,
                        "link_flair_text": None,
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_invalid_post_data_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response = _make_response({"data": "not a dict"})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_missing_data_key_uses_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == _REDDIT_POST_DEFAULTS
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {"error": "Not found"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_array_format(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="Nice post!")
        response = _make_response(
            [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": comment_data},
                            {"kind": "more", "data": {"id": "more1"}},
                        ]
                    }
                },
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comments",
                    "comments": [
                        {
                            "id": "c1",
                            "author": "commenter",
                            "body": "Nice post!",
                            "score": 15,
                            "created_utc": 1704067200,
                            "permalink": "/r/python/comments/abc/cmt1",
                            "is_submitter": True,
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_dict_format(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="Comment body")
        response = _make_response(
            {"comments": {"data": {"children": [{"kind": "t1", "data": comment_data}]}}}
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": {"body": "x"}}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result["comment_count"] == 1
        assert result["comments"][0] == {**_REDDIT_COMMENT_DEFAULTS, "body": "x"}
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comments",
                    "comments": [
                        {
                            "id": "",
                            "author": "",
                            "body": "x",
                            "score": 0,
                            "created_utc": 0,
                            "permalink": "",
                            "is_submitter": False,
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_truthy_is_submitter(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": {"body": "x", "is_submitter": True}}
                        ]
                    }
                },
            ]
        )
        reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["comments"][0]["is_submitter"] is True

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_response_without_data_key(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_listing_missing_children(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [{"data": {"children": []}}, {"data": {}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_listing_missing_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response([{"data": {"children": []}}, {}])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_missing_comments_key_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({})
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_single_element_array_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [{"data": {"children": [{"kind": "t1", "data": _make_reddit_comment_data()}]}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_non_dict_comments_listing_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response([{"data": {"children": []}}, "not a listing"])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_skips_non_t1(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "more", "data": {"id": "more1"}}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_skips_empty_body(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="")
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": comment_data}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_comments_after_hook_skips_invalid_comment_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": "oops"}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_at_most_50_comments(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comments = [
            {"kind": "t1", "data": _make_reddit_comment_data(id=f"c{i}", body=f"body {i}")}
            for i in range(51)
        ]
        response = _make_response(
            [{"data": {"children": []}}, {"data": {"children": comments}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result["comment_count"] == 51
        assert len(result["comments"]) == 51
        payload = writer.call_args[0][0]
        assert len(payload["reddit_data"]["comments"]) == 50
        assert payload["reddit_data"]["comments"][0]["id"] == "c0"
        assert payload["reddit_data"]["comments"][49]["id"] == "c49"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        comment_data = _make_reddit_comment_data()
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": comment_data}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"error": "Not found"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_comments_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "id": "new_post",
                "url": "https://reddit.com/r/python/new_post",
                "permalink": "/r/python/new_post",
            }
        )
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {
            "id": "new_post",
            "success": True,
            "message": "Content created successfully",
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post_created",
                    "data": {
                        "id": "new_post",
                        "url": "https://reddit.com/r/python/new_post",
                        "message": "Post created successfully!",
                        "permalink": "/r/python/new_post",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"id": "new_comment", "permalink": "/r/python/p1/new_comment"}
        )
        result = reddit_content_created_after_hook(
            "REDDIT_POST_REDDIT_COMMENT", "REDDIT", response
        )
        assert result == {
            "id": "new_comment",
            "success": True,
            "message": "Content created successfully",
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comment_created",
                    "data": {
                        "id": "new_comment",
                        "message": "Comment posted successfully!",
                        "permalink": "/r/python/p1/new_comment",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_unknown_tool_does_not_stream(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"id": "x"})
        result = reddit_content_created_after_hook(
            "REDDIT_EDIT_REDDIT_COMMENT_OR_POST", "REDDIT", response
        )
        assert result == {"id": "x", "success": True, "message": "Content created successfully"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        response = _make_response({"id": "new_post", "permalink": "/r/python/new_post"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {
            "id": "new_post",
            "success": True,
            "message": "Content created successfully",
        }

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_missing_data_key_uses_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {"id": "", "success": True, "message": "Content created successfully"}
        mock_log.error.assert_not_called()
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post_created",
                    "data": {
                        "id": "",
                        "url": "",
                        "message": "Post created successfully!",
                        "permalink": "",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_comment_missing_data_key_streams_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook(
            "REDDIT_POST_REDDIT_COMMENT", "REDDIT", response
        )
        assert result == {"id": "", "success": True, "message": "Content created successfully"}
        mock_log.error.assert_not_called()
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comment_created",
                    "data": {
                        "id": "",
                        "message": "Comment posted successfully!",
                        "permalink": "",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Forbidden"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {"error": "Forbidden"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_exception_returns_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.side_effect = RuntimeError("No writer")
        response = _make_response({"search_results": {}})
        result = reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        assert result == {"search_results": {}}
        _assert_logged_error(mock_log, "Error in reddit_search_after_hook", "No writer", "RuntimeError")


class TestRedditAfterHookExceptions:
    """Cover exception branches in the Reddit after-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_post_detail_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": {"id": "p1"}})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {"data": {"id": "p1"}}
        _assert_logged_error(mock_log, "Error in reddit_post_detail_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_post_detail_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        _assert_logged_error(mock_log, "Error in reddit_post_detail_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_comments_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response([{}, {"data": {"children": []}}])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == [{}, {"data": {"children": []}}]
        _assert_logged_error(mock_log, "Error in reddit_comments_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_comments_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {}
        _assert_logged_error(mock_log, "Error in reddit_comments_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_created_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"id": "new"})
        result = reddit_content_created_after_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", response)
        assert result == {"id": "new"}
        _assert_logged_error(
            mock_log, "Error in reddit_content_created_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_created_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in reddit_content_created_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"subreddit": "test"})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in reddit_content_before_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_delete_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_delete_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(mock_log, "Error in reddit_delete_before_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_retrieve_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_retrieve_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in reddit_retrieve_before_hook", "broken", "RuntimeError"
        )

