"""Twitter custom tool tests.

Tests the six custom Twitter tools registered via register_twitter_custom_tools:
  - CUSTOM_BATCH_FOLLOW
  - CUSTOM_BATCH_UNFOLLOW
  - CUSTOM_CREATE_THREAD
  - CUSTOM_SEARCH_USERS
  - CUSTOM_SCHEDULE_TWEET
  - CUSTOM_GATHER_CONTEXT

Strategy
--------
Each tool function is a nested closure defined inside
``register_twitter_custom_tools``.  We extract the real production functions
by calling ``register_twitter_custom_tools`` with a mock Composio whose
decorator simply records each registered function and returns it unchanged.

All outbound HTTP is made through ``app.utils.twitter_utils._http_client``
(an ``httpx.Client`` instance) and the free-function helpers in that same
module.  We patch those at the source so every code path inside the real
tool functions is exercised without a live network.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)
from app.utils.twitter_utils import (
    TWITTER_API_BASE,
    get_access_token,
    get_my_user_id,
    lookup_user_by_username,
    follow_user,
    unfollow_user,
    create_tweet,
    search_tweets,
    twitter_headers,
)

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-twitter-access-token"
FAKE_USER_ID = "111222333"
AUTH_CREDENTIALS: Dict[str, Any] = {"access_token": FAKE_TOKEN}


def _make_response(status_code: int = 200, json_data: Any = None, headers: dict = None) -> MagicMock:
    """Build a minimal mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.text = str(json_data)
    if status_code >= 400:
        error = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status.return_value = None
    return resp


TWITTER_TOOL_MODULE = "app.agents.tools.integrations.twitter_tool"


def _extract_twitter_tools() -> Dict[str, Any]:
    """
    Call the real register_twitter_custom_tools with a passthrough mock Composio
    and return a dict mapping function name -> real callable.

    The @composio.tools.custom_tool decorator is applied outermost, then @with_doc.
    We make custom_tool return a passthrough so the inner functions survive intact.
    """
    from app.agents.tools.integrations.twitter_tool import register_twitter_custom_tools

    captured: Dict[str, Any] = {}

    def _passthrough_decorator(fn: Any) -> Any:
        captured[fn.__name__] = fn
        return fn

    mock_composio = MagicMock()
    mock_composio.tools.custom_tool.return_value = _passthrough_decorator

    register_twitter_custom_tools(mock_composio)

    return captured


# ---------------------------------------------------------------------------
# get_access_token (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestGetAccessToken:
    def test_returns_token_when_present(self):
        assert get_access_token({"access_token": "tok123"}) == "tok123"

    def test_raises_when_missing(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({})

    def test_raises_when_none(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": None})


# ---------------------------------------------------------------------------
# twitter_headers (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestTwitterHeaders:
    def test_contains_bearer_token(self):
        headers = twitter_headers("mytoken")
        assert headers["Authorization"] == "Bearer mytoken"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# get_my_user_id (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestGetMyUserId:
    def test_happy_path(self):
        resp = _make_response(json_data={"data": {"id": "42"}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            result = get_my_user_id(FAKE_TOKEN)
        assert result == "42"

    def test_returns_none_on_http_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=_make_response(401)
        )
        with patch("app.utils.twitter_utils._http_client", mock_client):
            result = get_my_user_id(FAKE_TOKEN)
        assert result is None

    def test_returns_none_on_network_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("timeout")
        with patch("app.utils.twitter_utils._http_client", mock_client):
            result = get_my_user_id(FAKE_TOKEN)
        assert result is None


# ---------------------------------------------------------------------------
# lookup_user_by_username (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestLookupUserByUsername:
    def test_happy_path(self):
        user_data = {"id": "7", "username": "elonmusk", "name": "Elon Musk"}
        resp = _make_response(json_data={"data": user_data})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            result = lookup_user_by_username(FAKE_TOKEN, "elonmusk")
        assert result == user_data

    def test_strips_at_prefix(self):
        resp = _make_response(json_data={"data": {"id": "1"}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            lookup_user_by_username(FAKE_TOKEN, "@elonmusk")
            call_url = mock_client.get.call_args[0][0]
        assert "@" not in call_url
        assert "elonmusk" in call_url

    def test_returns_none_when_user_not_found(self):
        resp = _make_response(status_code=404)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp
        )
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            result = lookup_user_by_username(FAKE_TOKEN, "nobody")
        assert result is None


# ---------------------------------------------------------------------------
# follow_user / unfollow_user (utilities)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestFollowUnfollowUser:
    def test_follow_user_success(self):
        resp = _make_response(json_data={"data": {"following": True}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.return_value = resp
            result = follow_user(FAKE_TOKEN, FAKE_USER_ID, "999")
        assert result["success"] is True
        assert "data" in result

    def test_follow_user_http_error(self):
        bad_resp = _make_response(status_code=403)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=bad_resp
            )
            result = follow_user(FAKE_TOKEN, FAKE_USER_ID, "999")
        assert result["success"] is False
        assert "HTTP 403" in result["error"]

    def test_unfollow_user_success(self):
        resp = _make_response(json_data={"data": {"following": False}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.delete.return_value = resp
            result = unfollow_user(FAKE_TOKEN, FAKE_USER_ID, "999")
        assert result["success"] is True

    def test_unfollow_user_http_error(self):
        bad_resp = _make_response(status_code=429)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.delete.side_effect = httpx.HTTPStatusError(
                "429 Rate Limited", request=MagicMock(), response=bad_resp
            )
            result = unfollow_user(FAKE_TOKEN, FAKE_USER_ID, "999")
        assert result["success"] is False
        assert "HTTP 429" in result["error"]


# ---------------------------------------------------------------------------
# create_tweet (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCreateTweet:
    def test_simple_tweet(self):
        resp = _make_response(json_data={"data": {"id": "tweet-1", "text": "hello"}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.return_value = resp
            result = create_tweet(FAKE_TOKEN, "hello world")
        assert result["success"] is True
        assert result["data"]["id"] == "tweet-1"

    def test_reply_tweet_sends_reply_field(self):
        resp = _make_response(json_data={"data": {"id": "tweet-2"}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.return_value = resp
            create_tweet(FAKE_TOKEN, "reply text", reply_to_tweet_id="tweet-1")
            body = mock_client.post.call_args[1]["json"]
        assert body["reply"]["in_reply_to_tweet_id"] == "tweet-1"

    def test_tweet_with_media_ids(self):
        resp = _make_response(json_data={"data": {"id": "tweet-3"}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.return_value = resp
            create_tweet(FAKE_TOKEN, "pic", media_ids=["media-abc"])
            body = mock_client.post.call_args[1]["json"]
        assert body["media"]["media_ids"] == ["media-abc"]

    def test_rate_limit_returns_failure(self):
        bad_resp = _make_response(status_code=429)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=bad_resp
            )
            result = create_tweet(FAKE_TOKEN, "spam")
        assert result["success"] is False
        assert "HTTP 429" in result["error"]

    def test_auth_error_returns_failure(self):
        bad_resp = _make_response(status_code=401)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=bad_resp
            )
            result = create_tweet(FAKE_TOKEN, "auth fail")
        assert result["success"] is False
        assert "HTTP 401" in result["error"]


# ---------------------------------------------------------------------------
# search_tweets (utility)
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestSearchTweets:
    def _search_response(self):
        return _make_response(
            json_data={
                "data": [{"id": "t1", "text": "ai is cool", "author_id": "u1"}],
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "airesearcher",
                            "name": "AI Researcher",
                            "description": "I work on AI",
                            "verified": False,
                            "public_metrics": {"followers_count": 5000},
                        }
                    ]
                },
            }
        )

    def test_happy_path(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._search_response()
            result = search_tweets(FAKE_TOKEN, "AI research", max_results=10)
        assert result["success"] is True
        assert "data" in result

    def test_caps_max_results_at_100(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._search_response()
            search_tweets(FAKE_TOKEN, "test", max_results=999)
            params = mock_client.get.call_args[1]["params"]
        assert params["max_results"] == 100

    def test_http_error_returns_failure(self):
        bad_resp = _make_response(status_code=503)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "503", request=MagicMock(), response=bad_resp
            )
            result = search_tweets(FAKE_TOKEN, "query")
        assert result["success"] is False
        assert "HTTP 503" in result["error"]


# ---------------------------------------------------------------------------
# CUSTOM_BATCH_FOLLOW — real production function
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCustomBatchFollow:
    """Tests for CUSTOM_BATCH_FOLLOW using the real production function."""

    def setup_method(self):
        tools = _extract_twitter_tools()
        self._fn = tools["CUSTOM_BATCH_FOLLOW"]

    def _call(self, request: BatchFollowInput) -> Dict[str, Any]:
        """Invoke the real tool function with our fake auth_credentials."""
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            return self._fn(request, execute_request=None, auth_credentials=AUTH_CREDENTIALS)

    def test_follow_by_user_ids_success(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": {"id": FAKE_USER_ID}}
            )
            mock_client.post.return_value = _make_response(
                json_data={"data": {"following": True}}
            )
            result = self._call(BatchFollowInput(user_ids=["999"]))
        assert result["followed_count"] == 1
        assert result["failed_count"] == 0
        assert result["results"][0]["success"] is True

    def test_follow_by_usernames_success(self):
        user_lookup_resp = _make_response(
            json_data={"data": {"id": "42", "username": "target_user"}}
        )
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        follow_resp = _make_response(json_data={"data": {"following": True}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            # get calls: first = users/me, second = username lookup
            mock_client.get.side_effect = [my_id_resp, user_lookup_resp]
            mock_client.post.return_value = follow_resp
            result = self._call(BatchFollowInput(usernames=["target_user"]))
        assert result["followed_count"] == 1
        assert result["failed_count"] == 0

    def test_username_not_found_recorded_as_failure_and_raises(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        not_found_resp = _make_response(status_code=404)
        not_found_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=not_found_resp
        )

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = [my_id_resp, not_found_resp]
            # lookup returns None → username goes to failed list
            # all results are failures → RuntimeError raised by real production code
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                self._call(BatchFollowInput(usernames=["ghost_user"]))

    def test_raises_when_all_fail(self):
        bad_follow_resp = _make_response(status_code=403)
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=bad_follow_resp
            )
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                self._call(BatchFollowInput(user_ids=["999"]))

    def test_raises_when_neither_usernames_nor_user_ids(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self._call(BatchFollowInput())

    def test_raises_when_user_id_unavailable(self):
        error_resp = _make_response(status_code=401)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=error_resp
            )
            with pytest.raises(ValueError, match="Could not get authenticated user ID"):
                self._call(BatchFollowInput(user_ids=["999"]))

    def test_partial_success_does_not_raise(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_follow = _make_response(json_data={"data": {"following": True}})
        bad_resp = _make_response(status_code=403)

        follow_responses = [ok_follow, httpx.HTTPStatusError("403", request=MagicMock(), response=bad_resp)]

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = follow_responses
            result = self._call(BatchFollowInput(user_ids=["111", "222"]))
        assert result["followed_count"] == 1
        assert result["failed_count"] == 1

    def test_missing_access_token_raises(self):
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            with pytest.raises(ValueError, match="Missing access_token"):
                self._fn(BatchFollowInput(user_ids=["1"]), execute_request=None, auth_credentials={})


# ---------------------------------------------------------------------------
# CUSTOM_BATCH_UNFOLLOW — real production function
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCustomBatchUnfollow:
    def setup_method(self):
        tools = _extract_twitter_tools()
        self._fn = tools["CUSTOM_BATCH_UNFOLLOW"]

    def _call(self, request: BatchUnfollowInput) -> Dict[str, Any]:
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            return self._fn(request, execute_request=None, auth_credentials=AUTH_CREDENTIALS)

    def test_unfollow_by_user_ids_success(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_resp = _make_response(json_data={"data": {"following": False}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.delete.return_value = ok_resp
            result = self._call(BatchUnfollowInput(user_ids=["888"]))
        assert result["unfollowed_count"] == 1
        assert result["failed_count"] == 0

    def test_raises_when_all_unfollow_fail(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        bad_resp = _make_response(status_code=429)

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.delete.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=bad_resp
            )
            with pytest.raises(RuntimeError, match="Failed to unfollow all users"):
                self._call(BatchUnfollowInput(user_ids=["888"]))

    def test_raises_when_no_targets(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self._call(BatchUnfollowInput())

    def test_partial_success_does_not_raise(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_resp = _make_response(json_data={"data": {"following": False}})
        bad_resp = _make_response(status_code=403)

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.delete.side_effect = [
                ok_resp,
                httpx.HTTPStatusError("403", request=MagicMock(), response=bad_resp),
            ]
            result = self._call(BatchUnfollowInput(user_ids=["111", "222"]))
        assert result["unfollowed_count"] == 1
        assert result["failed_count"] == 1

    def test_unfollow_by_username_success(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        user_lookup_resp = _make_response(
            json_data={"data": {"id": "42", "username": "old_friend"}}
        )
        ok_resp = _make_response(json_data={"data": {"following": False}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = [my_id_resp, user_lookup_resp]
            mock_client.delete.return_value = ok_resp
            result = self._call(BatchUnfollowInput(usernames=["old_friend"]))
        assert result["unfollowed_count"] == 1

    def test_missing_access_token_raises(self):
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            with pytest.raises(ValueError, match="Missing access_token"):
                self._fn(BatchUnfollowInput(user_ids=["1"]), execute_request=None, auth_credentials={})


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_THREAD — real production function
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCustomCreateThread:
    def setup_method(self):
        tools = _extract_twitter_tools()
        self._fn = tools["CUSTOM_CREATE_THREAD"]

    def _call(self, request: CreateThreadInput) -> Dict[str, Any]:
        # CUSTOM_CREATE_THREAD captures _http_client from a local import inside
        # register_twitter_custom_tools.  That local binding points to the same
        # httpx.Client object as app.utils.twitter_utils._http_client.  We
        # therefore use patch.object on the actual client instance so that both
        # the module attribute and the closure's local reference see the mock.
        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            self._mock_post = mock_post
            self._mock_get = mock_get
            return self._fn(request, execute_request=None, auth_credentials=AUTH_CREDENTIALS)

    def _tweet_post_response(self, tweet_id: str) -> MagicMock:
        return _make_response(json_data={"data": {"id": tweet_id, "text": "..."}})

    def test_creates_two_tweet_thread(self):
        me_resp = _make_response(json_data={"data": {"username": "myhandle"}})

        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            mock_post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_get.return_value = me_resp
            result = self._fn(
                CreateThreadInput(tweets=["First tweet", "Second tweet"]),
                execute_request=None,
                auth_credentials=AUTH_CREDENTIALS,
            )

        assert result["thread_id"] == "t1"
        assert result["tweet_ids"] == ["t1", "t2"]
        assert result["tweet_count"] == 2
        assert "myhandle" in result["thread_url"]
        assert "t1" in result["thread_url"]

    def test_second_tweet_replies_to_first(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            mock_post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_get.return_value = me_resp
            self._fn(
                CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                execute_request=None,
                auth_credentials=AUTH_CREDENTIALS,
            )
            second_call_body = mock_post.call_args_list[1][1]["json"]
        assert second_call_body["reply"]["in_reply_to_tweet_id"] == "t1"

    def test_raises_for_single_tweet_at_model_level(self):
        # CreateThreadInput with only 1 item is blocked by pydantic min_length=2
        with pytest.raises(Exception):
            CreateThreadInput(tweets=["solo"])

    def test_raises_when_tweet_post_fails(self):
        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            mock_get.return_value = _make_response(json_data={"data": {"username": "u"}})
            mock_post.side_effect = [
                self._tweet_post_response("t1"),
                httpx.HTTPStatusError("429", request=MagicMock(), response=_make_response(429)),
            ]
            with pytest.raises(RuntimeError, match="Failed at tweet 2"):
                self._fn(
                    CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                    execute_request=None,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_falls_back_to_generic_username_on_me_api_error(self):
        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            mock_post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_get.side_effect = httpx.ConnectError("network down")
            result = self._fn(
                CreateThreadInput(tweets=["A", "B"]),
                execute_request=None,
                auth_credentials=AUTH_CREDENTIALS,
            )
        # Falls back to "i" in URL
        assert result["thread_url"] == "https://twitter.com/i/status/t1"

    def test_thread_with_media_ids(self):
        # media_ids must be List[List[str]] - each element is a list of strings
        import app.utils.twitter_utils as tw_utils

        with (
            patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None),
            patch.object(tw_utils._http_client, "post") as mock_post,
            patch.object(tw_utils._http_client, "get") as mock_get,
        ):
            mock_post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_get.return_value = _make_response(json_data={"data": {"username": "u"}})
            self._fn(
                CreateThreadInput(
                    tweets=["Tweet 1", "Tweet 2"],
                    media_ids=[["media-1"], []],
                ),
                execute_request=None,
                auth_credentials=AUTH_CREDENTIALS,
            )
            first_call_body = mock_post.call_args_list[0][1]["json"]
        assert first_call_body["media"]["media_ids"] == ["media-1"]

    def test_missing_access_token_raises(self):
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            with pytest.raises(ValueError, match="Missing access_token"):
                self._fn(CreateThreadInput(tweets=["A", "B"]), execute_request=None, auth_credentials={})


# ---------------------------------------------------------------------------
# CUSTOM_SEARCH_USERS — real production function
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCustomSearchUsers:
    def setup_method(self):
        tools = _extract_twitter_tools()
        self._fn = tools["CUSTOM_SEARCH_USERS"]

    def _call(self, request: SearchUsersInput) -> Dict[str, Any]:
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            return self._fn(request, execute_request=None, auth_credentials=AUTH_CREDENTIALS)

    def _build_search_resp(self, users: list) -> MagicMock:
        return _make_response(
            json_data={
                "data": [{"id": "tw1", "text": "hello", "author_id": users[0]["id"]}],
                "includes": {"users": users},
            }
        )

    def test_returns_users_from_tweet_authors(self):
        users = [
            {
                "id": "u1",
                "username": "aidev",
                "name": "AI Dev",
                "description": "Building AI",
                "verified": False,
                "public_metrics": {"followers_count": 1200},
            }
        ]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._build_search_resp(users)
            result = self._call(SearchUsersInput(query="AI developer"))
        assert result["count"] == 1
        assert result["users"][0]["username"] == "aidev"
        assert result["users"][0]["followers"] == 1200

    def test_appends_retweet_filter_to_query(self):
        users = [{"id": "u1", "username": "x", "name": "X", "description": "", "verified": False, "public_metrics": {}}]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._build_search_resp(users)
            self._call(SearchUsersInput(query="python dev"))
            params = mock_client.get.call_args[1]["params"]
        assert "-is:retweet" in params["query"]
        assert "python dev" in params["query"]

    def test_deduplicates_users(self):
        duplicate_user = {
            "id": "u1",
            "username": "dup",
            "name": "Dup User",
            "description": "",
            "verified": False,
            "public_metrics": {"followers_count": 100},
        }
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={
                    "data": [{"id": "tw1", "author_id": "u1"}, {"id": "tw2", "author_id": "u1"}],
                    "includes": {"users": [duplicate_user, duplicate_user]},
                }
            )
            result = self._call(SearchUsersInput(query="dedup test"))
        assert result["count"] == 1

    def test_respects_max_results(self):
        users = [
            {"id": str(i), "username": f"user{i}", "name": f"U{i}", "description": "", "verified": False, "public_metrics": {}}
            for i in range(10)
        ]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": [], "includes": {"users": users}}
            )
            result = self._call(SearchUsersInput(query="many users", max_results=3))
        assert result["count"] == 3

    def test_raises_on_search_failure(self):
        bad_resp = _make_response(status_code=429)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=bad_resp
            )
            with pytest.raises(RuntimeError, match="Search failed"):
                self._call(SearchUsersInput(query="rate limited query"))

    def test_truncates_description_to_150_chars(self):
        long_desc = "x" * 300
        users = [
            {
                "id": "u1",
                "username": "verbose",
                "name": "Verbose User",
                "description": long_desc,
                "verified": False,
                "public_metrics": {"followers_count": 0},
            }
        ]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._build_search_resp(users)
            result = self._call(SearchUsersInput(query="verbose"))
        assert len(result["users"][0]["description"]) == 150

    def test_returns_empty_when_no_users_in_includes(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": [], "includes": {}}
            )
            result = self._call(SearchUsersInput(query="nobody"))
        assert result["count"] == 0
        assert result["users"] == []

    def test_missing_access_token_raises(self):
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            with pytest.raises(ValueError, match="Missing access_token"):
                self._fn(SearchUsersInput(query="test"), execute_request=None, auth_credentials={})


# ---------------------------------------------------------------------------
# CUSTOM_SCHEDULE_TWEET — real production function
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestCustomScheduleTweet:
    def setup_method(self):
        tools = _extract_twitter_tools()
        self._fn = tools["CUSTOM_SCHEDULE_TWEET"]

    def _call(self, request: ScheduleTweetInput) -> Dict[str, Any]:
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            return self._fn(request, execute_request=None, auth_credentials=AUTH_CREDENTIALS)

    def test_returns_draft_with_all_fields(self):
        result = self._call(
            ScheduleTweetInput(
                text="Hello future!",
                scheduled_time="2026-12-25T10:00:00Z",
                media_urls=["https://example.com/img.png"],
                reply_to_tweet_id="tweet-99",
            )
        )
        assert result["draft"]["text"] == "Hello future!"
        assert result["draft"]["scheduled_time"] == "2026-12-25T10:00:00Z"
        assert result["draft"]["media_urls"] == ["https://example.com/img.png"]
        assert result["draft"]["reply_to_tweet_id"] == "tweet-99"

    def test_message_contains_scheduled_time(self):
        result = self._call(
            ScheduleTweetInput(text="Reminder!", scheduled_time="2026-01-01T00:00:00Z")
        )
        assert "2026-01-01T00:00:00Z" in result["message"]

    def test_optional_fields_default_to_none(self):
        result = self._call(
            ScheduleTweetInput(text="Simple tweet", scheduled_time="2026-06-15T09:00:00Z")
        )
        assert result["draft"]["media_urls"] is None
        assert result["draft"]["reply_to_tweet_id"] is None

    def test_no_auth_required_for_draft_creation(self):
        # CUSTOM_SCHEDULE_TWEET creates a local draft without calling the Twitter API,
        # so it does not validate auth_credentials.
        with patch(f"{TWITTER_TOOL_MODULE}.get_stream_writer", return_value=None):
            result = self._fn(
                ScheduleTweetInput(text="no auth needed", scheduled_time="2026-01-01T00:00:00Z"),
                execute_request=None,
                auth_credentials={},
            )
        assert result["draft"]["text"] == "no auth needed"

    def test_does_not_make_any_http_calls(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            self._call(
                ScheduleTweetInput(text="offline", scheduled_time="2026-01-01T00:00:00Z")
            )
        mock_client.post.assert_not_called()
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# register_twitter_custom_tools returns correct tool name list
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestRegisterTwitterCustomTools:
    def test_returns_all_tool_names(self):
        from app.agents.tools.integrations.twitter_tool import register_twitter_custom_tools

        mock_composio = MagicMock()
        mock_composio.tools.custom_tool.return_value = lambda fn: fn

        names = register_twitter_custom_tools(mock_composio)

        assert set(names) == {
            "TWITTER_CUSTOM_BATCH_FOLLOW",
            "TWITTER_CUSTOM_BATCH_UNFOLLOW",
            "TWITTER_CUSTOM_CREATE_THREAD",
            "TWITTER_CUSTOM_SEARCH_USERS",
            "TWITTER_CUSTOM_SCHEDULE_TWEET",
            "TWITTER_CUSTOM_GATHER_CONTEXT",
        }
        assert len(names) == 6
