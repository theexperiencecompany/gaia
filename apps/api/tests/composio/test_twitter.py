"""Unit tests for twitter_tool.py custom tool handler functions.

These tests exercise every inner function registered by
``register_twitter_custom_tools`` by calling those functions directly after
extracting them from a mock Composio client.  They do **not** require real
API credentials; all network I/O is patched at the ``_http_client`` boundary
in ``app.utils.twitter_utils``.

What is being tested
--------------------
All five handler functions defined inside
``app.agents.tools.integrations.twitter_tool.register_twitter_custom_tools``:

* CUSTOM_BATCH_FOLLOW
* CUSTOM_BATCH_UNFOLLOW
* CUSTOM_CREATE_THREAD
* CUSTOM_SEARCH_USERS
* CUSTOM_SCHEDULE_TWEET

For each handler the test suite covers:

* Happy path – HTTP stubs return success; verify return value structure.
* Error path – HTTP raises an error or returns bad data; verify the handler
  propagates or raises the expected exception type.

Markers
-------
All tests are tagged ``@pytest.mark.composio`` because they live in the
``tests/composio/`` directory (auto-marked by the conftest) and we add the
marker explicitly at class level for clarity.

Import coupling
---------------
The import at the top of this file::

    from app.agents.tools.integrations.twitter_tool import register_twitter_custom_tools

means that if ``twitter_tool.py`` is deleted or the function is renamed,
**every test in this module will fail**, which is the intended behaviour.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.agents.tools.integrations.twitter_tool import register_twitter_custom_tools
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)
from app.utils.twitter_utils import (
    create_tweet,
    follow_user,
    get_access_token,
    get_my_user_id,
    lookup_user_by_username,
    search_tweets,
    twitter_headers,
    unfollow_user,
)


@pytest.fixture(autouse=True)
def mock_stream_writer():
    """Patch get_stream_writer in twitter_tool for every test in this module."""
    with patch(
        "app.agents.tools.integrations.twitter_tool.get_stream_writer",
        return_value=lambda _: None,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-twitter-access-token"
FAKE_USER_ID = "111222333"
AUTH_CREDENTIALS: Dict[str, Any] = {"access_token": FAKE_TOKEN}
EXECUTE_REQUEST_STUB = None  # handlers never use this arg; keep it None


def _make_response(
    status_code: int = 200, json_data: Any = None, headers: dict | None = None
) -> MagicMock:
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


def _make_composio_mock() -> tuple[MagicMock, dict[str, Any]]:
    """Return a (composio_mock, handlers) pair.

    Calling ``register_twitter_custom_tools(composio_mock)`` causes the
    decorator ``composio.tools.custom_tool(toolkit=...)`` to be invoked for
    each handler.  We capture every decorated function so the tests can call
    them directly.
    """
    captured: dict[str, Any] = {}

    def _fake_custom_tool(toolkit: str):
        """Mimic @composio.tools.custom_tool(toolkit=...) decorator."""

        def _decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return _decorator

    composio = MagicMock()
    composio.tools.custom_tool.side_effect = _fake_custom_tool

    with patch("langgraph.config.get_stream_writer", return_value=lambda _: None):
        register_twitter_custom_tools(composio)

    return composio, captured


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


# ===========================================================================
# Tests for CUSTOM_BATCH_FOLLOW
# ===========================================================================


@pytest.mark.composio
class TestCustomBatchFollow:
    """Tests for the CUSTOM_BATCH_FOLLOW handler captured from production."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_BATCH_FOLLOW"]

    def test_follow_by_user_ids_success(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": {"id": FAKE_USER_ID}}
            )
            mock_client.post.return_value = _make_response(
                json_data={"data": {"following": True}}
            )
            result = self.handler(
                request=BatchFollowInput(user_ids=["999"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
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
            mock_client.get.side_effect = [my_id_resp, user_lookup_resp]
            mock_client.post.return_value = follow_resp
            result = self.handler(
                request=BatchFollowInput(usernames=["target_user"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["followed_count"] == 1
        assert result["failed_count"] == 0

    def test_username_not_found_recorded_as_failure(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        not_found_resp = _make_response(status_code=404)
        not_found_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=not_found_resp
        )

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = [my_id_resp, not_found_resp]
            # All entries fail (one not-found username, no user_ids_to_process),
            # so the production code raises RuntimeError when failed_count == len(results).
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                self.handler(
                    request=BatchFollowInput(usernames=["ghost_user"]),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_username_not_found_appears_in_failure_results(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_lookup_resp = _make_response(
            json_data={"data": {"id": "42", "username": "real_user"}}
        )
        not_found_resp = _make_response(status_code=404)
        not_found_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=not_found_resp
        )
        follow_resp = _make_response(json_data={"data": {"following": True}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            # get: users/me, lookup real_user (success), lookup ghost_user (404)
            mock_client.get.side_effect = [my_id_resp, ok_lookup_resp, not_found_resp]
            mock_client.post.return_value = follow_resp
            result = self.handler(
                request=BatchFollowInput(usernames=["real_user", "ghost_user"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )

        assert result["followed_count"] == 1
        assert result["failed_count"] == 1
        assert len(result["results"]) == 2
        failed_entries = [r for r in result["results"] if not r["success"]]
        assert len(failed_entries) == 1
        assert failed_entries[0]["username"] == "ghost_user"
        assert failed_entries[0]["error"] == "User not found"
        successful_entries = [r for r in result["results"] if r["success"]]
        assert len(successful_entries) == 1
        assert successful_entries[0]["username"] == "real_user"

    def test_raises_when_all_fail(self):
        bad_follow_resp = _make_response(status_code=403)
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=bad_follow_resp
            )
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                self.handler(
                    request=BatchFollowInput(user_ids=["999"]),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_raises_when_neither_usernames_nor_user_ids(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self.handler(
                    request=BatchFollowInput(),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_raises_when_user_id_unavailable(self):
        error_resp = _make_response(status_code=401)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=error_resp
            )
            with pytest.raises(ValueError, match="Could not get authenticated user ID"):
                self.handler(
                    request=BatchFollowInput(user_ids=["999"]),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_partial_success_does_not_raise(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_follow = _make_response(json_data={"data": {"following": True}})
        bad_resp = _make_response(status_code=403)

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = [
                ok_follow,
                httpx.HTTPStatusError("403", request=MagicMock(), response=bad_resp),
            ]
            result = self.handler(
                request=BatchFollowInput(user_ids=["111", "222"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["followed_count"] == 1
        assert result["failed_count"] == 1

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=BatchFollowInput(user_ids=["1"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )


# ===========================================================================
# Tests for CUSTOM_BATCH_UNFOLLOW
# ===========================================================================


@pytest.mark.composio
class TestCustomBatchUnfollow:
    """Tests for the CUSTOM_BATCH_UNFOLLOW handler captured from production."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_BATCH_UNFOLLOW"]

    def test_unfollow_by_user_ids_success(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_resp = _make_response(json_data={"data": {"following": False}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.delete.return_value = ok_resp
            result = self.handler(
                request=BatchUnfollowInput(user_ids=["888"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
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
                self.handler(
                    request=BatchUnfollowInput(user_ids=["888"]),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_raises_when_no_targets(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self.handler(
                    request=BatchUnfollowInput(),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

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
            result = self.handler(
                request=BatchUnfollowInput(user_ids=["111", "222"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
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
            result = self.handler(
                request=BatchUnfollowInput(usernames=["old_friend"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["unfollowed_count"] == 1

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=BatchUnfollowInput(user_ids=["1"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )


# ===========================================================================
# Tests for CUSTOM_CREATE_THREAD
# ===========================================================================


@pytest.mark.composio
class TestCustomCreateThread:
    """Tests for the CUSTOM_CREATE_THREAD handler captured from production."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_CREATE_THREAD"]

    def _tweet_post_response(self, tweet_id: str) -> MagicMock:
        return _make_response(json_data={"data": {"id": tweet_id, "text": "..."}})

    def test_creates_two_tweet_thread(self):
        me_resp = _make_response(json_data={"data": {"username": "myhandle"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.return_value = me_resp
            result = self.handler(
                request=CreateThreadInput(tweets=["First tweet", "Second tweet"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )

        assert result["thread_id"] == "t1"
        assert result["tweet_ids"] == ["t1", "t2"]
        assert result["tweet_count"] == 2
        assert "myhandle" in result["thread_url"]
        assert "t1" in result["thread_url"]

    def test_second_tweet_replies_to_first(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.return_value = me_resp
            self.handler(
                request=CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
            second_call_body = mock_client.post.call_args_list[1][1]["json"]
        assert second_call_body["reply"]["in_reply_to_tweet_id"] == "t1"

    def test_raises_for_single_tweet(self):
        # CreateThreadInput with only 1 item is blocked by pydantic min_length=2
        with pytest.raises(Exception):
            CreateThreadInput(tweets=["solo"])

    def test_raises_when_tweet_post_fails(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = me_resp
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                httpx.HTTPStatusError(
                    "429", request=MagicMock(), response=_make_response(429)
                ),
            ]
            with pytest.raises(RuntimeError, match="Failed at tweet 2"):
                self.handler(
                    request=CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

    def test_falls_back_to_generic_username_on_me_api_error(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.side_effect = httpx.ConnectError("network down")
            result = self.handler(
                request=CreateThreadInput(tweets=["A", "B"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["thread_url"] == "https://twitter.com/i/status/t1"

    def test_thread_with_media_ids(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.return_value = me_resp
            self.handler(
                request=CreateThreadInput(
                    tweets=["Tweet 1", "Tweet 2"],
                    media_ids=[["media-1"], None],
                ),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
            first_call_body = mock_client.post.call_args_list[0][1]["json"]
        assert first_call_body["media"]["media_ids"] == ["media-1"]

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=CreateThreadInput(tweets=["A", "B"]),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )


# ===========================================================================
# Tests for CUSTOM_SEARCH_USERS
# ===========================================================================


@pytest.mark.composio
class TestCustomSearchUsers:
    """Tests for the CUSTOM_SEARCH_USERS handler captured from production."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_SEARCH_USERS"]

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
            result = self.handler(
                request=SearchUsersInput(query="AI developer"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["count"] == 1
        assert result["users"][0]["username"] == "aidev"
        assert result["users"][0]["followers"] == 1200

    def test_appends_retweet_filter_to_query(self):
        users = [
            {
                "id": "u1",
                "username": "x",
                "name": "X",
                "description": "",
                "verified": False,
                "public_metrics": {},
            }
        ]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._build_search_resp(users)
            self.handler(
                request=SearchUsersInput(query="python dev"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
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
                    "data": [
                        {"id": "tw1", "author_id": "u1"},
                        {"id": "tw2", "author_id": "u1"},
                    ],
                    "includes": {"users": [duplicate_user, duplicate_user]},
                }
            )
            result = self.handler(
                request=SearchUsersInput(query="dedup test"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["count"] == 1

    def test_respects_max_results(self):
        users = [
            {
                "id": str(i),
                "username": f"user{i}",
                "name": f"U{i}",
                "description": "",
                "verified": False,
                "public_metrics": {},
            }
            for i in range(10)
        ]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": [], "includes": {"users": users}}
            )
            result = self.handler(
                request=SearchUsersInput(query="many users", max_results=3),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["count"] == 3

    def test_raises_on_search_failure(self):
        bad_resp = _make_response(status_code=429)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=bad_resp
            )
            with pytest.raises(RuntimeError, match="Search failed"):
                self.handler(
                    request=SearchUsersInput(query="rate limited query"),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDENTIALS,
                )

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
            result = self.handler(
                request=SearchUsersInput(query="verbose"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert len(result["users"][0]["description"]) == 150

    def test_returns_empty_when_no_users_in_includes(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": [], "includes": {}}
            )
            result = self.handler(
                request=SearchUsersInput(query="nobody"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        assert result["count"] == 0
        assert result["users"] == []

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=SearchUsersInput(query="test"),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )


# ===========================================================================
# Tests for CUSTOM_SCHEDULE_TWEET
# ===========================================================================


@pytest.mark.composio
class TestCustomScheduleTweet:
    """Tests for the CUSTOM_SCHEDULE_TWEET handler captured from production."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_SCHEDULE_TWEET"]

    def test_returns_draft_with_all_fields(self):
        result = self.handler(
            request=ScheduleTweetInput(
                text="Hello future!",
                scheduled_time="2026-12-25T10:00:00Z",
                media_urls=["https://example.com/img.png"],
                reply_to_tweet_id="tweet-99",
            ),
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=AUTH_CREDENTIALS,
        )
        assert result["draft"]["text"] == "Hello future!"
        assert result["draft"]["scheduled_time"] == "2026-12-25T10:00:00Z"
        assert result["draft"]["media_urls"] == ["https://example.com/img.png"]
        assert result["draft"]["reply_to_tweet_id"] == "tweet-99"

    def test_message_contains_scheduled_time(self):
        result = self.handler(
            request=ScheduleTweetInput(
                text="Reminder!", scheduled_time="2026-01-01T00:00:00Z"
            ),
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=AUTH_CREDENTIALS,
        )
        assert "2026-01-01T00:00:00Z" in result["message"]

    def test_optional_fields_default_to_none(self):
        result = self.handler(
            request=ScheduleTweetInput(
                text="Simple tweet", scheduled_time="2026-06-15T09:00:00Z"
            ),
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=AUTH_CREDENTIALS,
        )
        assert result["draft"]["media_urls"] is None
        assert result["draft"]["reply_to_tweet_id"] is None

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=ScheduleTweetInput(
                    text="no auth", scheduled_time="2026-01-01T00:00:00Z"
                ),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )

    def test_does_not_make_any_http_calls(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            self.handler(
                request=ScheduleTweetInput(
                    text="offline", scheduled_time="2026-01-01T00:00:00Z"
                ),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDENTIALS,
            )
        mock_client.post.assert_not_called()
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# register_twitter_custom_tools returns correct tool name list
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterTwitterCustomTools:
    def test_returns_all_six_tool_names(self):
        mock_composio = MagicMock()
        mock_composio.tools.custom_tool.return_value = lambda fn: fn

        with patch("langgraph.config.get_stream_writer", return_value=lambda _: None):
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
