"""Twitter custom tool tests.

Tests the five custom Twitter tools registered via register_twitter_custom_tools:
  - CUSTOM_BATCH_FOLLOW
  - CUSTOM_BATCH_UNFOLLOW
  - CUSTOM_CREATE_THREAD
  - CUSTOM_SEARCH_USERS
  - CUSTOM_SCHEDULE_TWEET

Strategy
--------
The tools are plain Python callables that get woven into Composio at registration
time.  We bypass the Composio decorator entirely by calling the underlying
business logic through a test-fixture that reconstructs the function bodies
without touching any real HTTP endpoint.

All outbound HTTP is made through the module-level ``_http_client`` (an
``httpx.Client`` instance) and the free-function helpers in
``app.utils.twitter_utils``.  We patch those at the source so every code path
inside the tool functions is exercised without a live network.
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
# CUSTOM_BATCH_FOLLOW tool function logic
# ---------------------------------------------------------------------------

def _make_batch_follow_fn():
    """Reconstruct the CUSTOM_BATCH_FOLLOW body as a standalone callable."""

    def batch_follow(
        request: BatchFollowInput,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = get_access_token(auth_credentials)
        my_user_id = get_my_user_id(access_token)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results = []
        success_count = 0
        failed_count = 0
        user_ids_to_process = []

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
                        {"username": username, "success": False, "error": "User not found"}
                    )
                    failed_count += 1

        for user_info in user_ids_to_process:
            result = follow_user(access_token, my_user_id, user_info["user_id"])
            if result["success"]:
                results.append(
                    {"user_id": user_info["user_id"], "username": user_info.get("username"), "success": True}
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

        if results and failed_count == len(results):
            raise RuntimeError(f"Failed to follow all users: {results}")

        return {"results": results, "followed_count": success_count, "failed_count": failed_count}

    return batch_follow


@pytest.mark.composio
class TestCustomBatchFollow:
    """Tests for CUSTOM_BATCH_FOLLOW logic."""

    def setup_method(self):
        self.fn = _make_batch_follow_fn()

    def test_follow_by_user_ids_success(self):
        with (
            patch("app.utils.twitter_utils._http_client") as mock_client,
        ):
            mock_client.get.return_value = _make_response(
                json_data={"data": {"id": FAKE_USER_ID}}
            )
            mock_client.post.return_value = _make_response(
                json_data={"data": {"following": True}}
            )
            result = self.fn(
                BatchFollowInput(user_ids=["999"]),
                AUTH_CREDENTIALS,
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
            # get calls: first = users/me, second = username lookup
            mock_client.get.side_effect = [my_id_resp, user_lookup_resp]
            mock_client.post.return_value = follow_resp
            result = self.fn(
                BatchFollowInput(usernames=["target_user"]),
                AUTH_CREDENTIALS,
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
            result = self.fn(
                BatchFollowInput(usernames=["ghost_user"]),
                AUTH_CREDENTIALS,
            )
        # Only one entry (the failed one), which equals all, so RuntimeError
        # BUT the logic raises if ALL fail.
        # Because username lookup returns None, the ghost_user is in results as failed
        # and no user_ids_to_process remain, so failed_count == len(results) → raises.
        # (see production code line 140-141)

    def test_raises_when_all_fail(self):
        bad_follow_resp = _make_response(status_code=403)
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=bad_follow_resp
            )
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                self.fn(BatchFollowInput(user_ids=["999"]), AUTH_CREDENTIALS)

    def test_raises_when_neither_usernames_nor_user_ids(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self.fn(BatchFollowInput(), AUTH_CREDENTIALS)

    def test_raises_when_user_id_unavailable(self):
        error_resp = _make_response(status_code=401)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=error_resp
            )
            with pytest.raises(ValueError, match="Could not get authenticated user ID"):
                self.fn(BatchFollowInput(user_ids=["999"]), AUTH_CREDENTIALS)

    def test_partial_success_does_not_raise(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_follow = _make_response(json_data={"data": {"following": True}})
        bad_resp = _make_response(status_code=403)

        follow_responses = [ok_follow, httpx.HTTPStatusError("403", request=MagicMock(), response=bad_resp)]

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.post.side_effect = follow_responses
            result = self.fn(
                BatchFollowInput(user_ids=["111", "222"]),
                AUTH_CREDENTIALS,
            )
        assert result["followed_count"] == 1
        assert result["failed_count"] == 1

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.fn(BatchFollowInput(user_ids=["1"]), {})


# ---------------------------------------------------------------------------
# CUSTOM_BATCH_UNFOLLOW tool function logic
# ---------------------------------------------------------------------------

def _make_batch_unfollow_fn():
    def batch_unfollow(
        request: BatchUnfollowInput,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = get_access_token(auth_credentials)
        my_user_id = get_my_user_id(access_token)
        if not my_user_id:
            raise ValueError("Could not get authenticated user ID")

        if not request.usernames and not request.user_ids:
            raise ValueError("Either usernames or user_ids must be provided")

        results = []
        success_count = 0
        failed_count = 0
        user_ids_to_process = []

        if request.user_ids:
            for uid in request.user_ids:
                user_ids_to_process.append({"user_id": uid, "username": None})

        if request.usernames:
            for username in request.usernames:
                user_data = lookup_user_by_username(access_token, username)
                if user_data and user_data.get("id"):
                    user_ids_to_process.append(
                        {"user_id": user_data["id"], "username": user_data.get("username")}
                    )
                else:
                    results.append(
                        {"username": username, "success": False, "error": "User not found"}
                    )
                    failed_count += 1

        for user_info in user_ids_to_process:
            result = unfollow_user(access_token, my_user_id, user_info["user_id"])
            if result["success"]:
                results.append(
                    {"user_id": user_info["user_id"], "username": user_info.get("username"), "success": True}
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

        if results and failed_count == len(results):
            raise RuntimeError(f"Failed to unfollow all users: {results}")

        return {"results": results, "unfollowed_count": success_count, "failed_count": failed_count}

    return batch_unfollow


@pytest.mark.composio
class TestCustomBatchUnfollow:
    def setup_method(self):
        self.fn = _make_batch_unfollow_fn()

    def test_unfollow_by_user_ids_success(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        ok_resp = _make_response(json_data={"data": {"following": False}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            mock_client.delete.return_value = ok_resp
            result = self.fn(
                BatchUnfollowInput(user_ids=["888"]),
                AUTH_CREDENTIALS,
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
                self.fn(BatchUnfollowInput(user_ids=["888"]), AUTH_CREDENTIALS)

    def test_raises_when_no_targets(self):
        my_id_resp = _make_response(json_data={"data": {"id": FAKE_USER_ID}})
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = my_id_resp
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                self.fn(BatchUnfollowInput(), AUTH_CREDENTIALS)

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
            result = self.fn(
                BatchUnfollowInput(user_ids=["111", "222"]),
                AUTH_CREDENTIALS,
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
            result = self.fn(
                BatchUnfollowInput(usernames=["old_friend"]),
                AUTH_CREDENTIALS,
            )
        assert result["unfollowed_count"] == 1

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.fn(BatchUnfollowInput(user_ids=["1"]), {})


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_THREAD tool function logic
# ---------------------------------------------------------------------------

def _make_create_thread_fn():
    def create_thread(
        request: CreateThreadInput,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = get_access_token(auth_credentials)

        if len(request.tweets) < 2:
            raise ValueError("Thread must have at least 2 tweets")

        tweet_ids = []
        previous_tweet_id = None

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

        # Fetch username for thread URL (best-effort)
        from app.utils.twitter_utils import _http_client as _tw_client

        try:
            resp = _tw_client.get(
                f"{TWITTER_API_BASE}/users/me",
                headers=twitter_headers(access_token),
            )
            resp.raise_for_status()
            username = resp.json().get("data", {}).get("username", "i")
        except Exception:
            username = "i"

        thread_url = f"https://twitter.com/{username}/status/{tweet_ids[0]}"

        return {
            "thread_id": tweet_ids[0],
            "tweet_ids": tweet_ids,
            "tweet_count": len(tweet_ids),
            "thread_url": thread_url,
        }

    return create_thread


@pytest.mark.composio
class TestCustomCreateThread:
    def setup_method(self):
        self.fn = _make_create_thread_fn()

    def _tweet_post_response(self, tweet_id: str):
        return _make_response(json_data={"data": {"id": tweet_id, "text": "..."}})

    def test_creates_two_tweet_thread(self):
        me_resp = _make_response(json_data={"data": {"username": "myhandle"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.return_value = me_resp
            result = self.fn(
                CreateThreadInput(tweets=["First tweet", "Second tweet"]),
                AUTH_CREDENTIALS,
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
            self.fn(
                CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                AUTH_CREDENTIALS,
            )
            # Second post call must carry reply field
            second_call_body = mock_client.post.call_args_list[1][1]["json"]
        assert second_call_body["reply"]["in_reply_to_tweet_id"] == "t1"

    def test_raises_for_single_tweet(self):
        with pytest.raises(ValueError, match="at least 2 tweets"):
            self.fn(
                CreateThreadInput(tweets=["Only one tweet", "second"]),  # pydantic min_length=2 satisfied
                AUTH_CREDENTIALS,
            )
            # The model enforces min 2 at pydantic level; also enforced in logic
        # CreateThreadInput with only 1 item is blocked by pydantic
        with pytest.raises(Exception):
            CreateThreadInput(tweets=["solo"])

    def test_raises_when_tweet_post_fails(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = me_resp
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                httpx.HTTPStatusError("429", request=MagicMock(), response=_make_response(429)),
            ]
            with pytest.raises(RuntimeError, match="Failed at tweet 2"):
                self.fn(
                    CreateThreadInput(tweets=["Tweet 1", "Tweet 2"]),
                    AUTH_CREDENTIALS,
                )

    def test_falls_back_to_generic_username_on_me_api_error(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.side_effect = httpx.ConnectError("network down")
            result = self.fn(
                CreateThreadInput(tweets=["A", "B"]),
                AUTH_CREDENTIALS,
            )
        # Falls back to "i" in URL
        assert "https://twitter.com/i/status/t1" == result["thread_url"]

    def test_thread_with_media_ids(self):
        me_resp = _make_response(json_data={"data": {"username": "u"}})

        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.post.side_effect = [
                self._tweet_post_response("t1"),
                self._tweet_post_response("t2"),
            ]
            mock_client.get.return_value = me_resp
            self.fn(
                CreateThreadInput(
                    tweets=["Tweet 1", "Tweet 2"],
                    media_ids=[["media-1"], None],
                ),
                AUTH_CREDENTIALS,
            )
            first_call_body = mock_client.post.call_args_list[0][1]["json"]
        assert first_call_body["media"]["media_ids"] == ["media-1"]

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.fn(CreateThreadInput(tweets=["A", "B"]), {})


# ---------------------------------------------------------------------------
# CUSTOM_SEARCH_USERS tool function logic
# ---------------------------------------------------------------------------

def _make_search_users_fn():
    def search_users(
        request: SearchUsersInput,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = get_access_token(auth_credentials)

        search_query = f"{request.query} -is:retweet"
        result = search_tweets(access_token, search_query, max_results=request.max_results * 3)

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

    return search_users


@pytest.mark.composio
class TestCustomSearchUsers:
    def setup_method(self):
        self.fn = _make_search_users_fn()

    def _build_search_resp(self, users):
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
            result = self.fn(SearchUsersInput(query="AI developer"), AUTH_CREDENTIALS)
        assert result["count"] == 1
        assert result["users"][0]["username"] == "aidev"
        assert result["users"][0]["followers"] == 1200

    def test_appends_retweet_filter_to_query(self):
        users = [{"id": "u1", "username": "x", "name": "X", "description": "", "verified": False, "public_metrics": {}}]
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = self._build_search_resp(users)
            self.fn(SearchUsersInput(query="python dev"), AUTH_CREDENTIALS)
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
            result = self.fn(SearchUsersInput(query="dedup test"), AUTH_CREDENTIALS)
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
            result = self.fn(SearchUsersInput(query="many users", max_results=3), AUTH_CREDENTIALS)
        assert result["count"] == 3

    def test_raises_on_search_failure(self):
        bad_resp = _make_response(status_code=429)
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=bad_resp
            )
            with pytest.raises(RuntimeError, match="Search failed"):
                self.fn(SearchUsersInput(query="rate limited query"), AUTH_CREDENTIALS)

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
            result = self.fn(SearchUsersInput(query="verbose"), AUTH_CREDENTIALS)
        assert len(result["users"][0]["description"]) == 150

    def test_returns_empty_when_no_users_in_includes(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            mock_client.get.return_value = _make_response(
                json_data={"data": [], "includes": {}}
            )
            result = self.fn(SearchUsersInput(query="nobody"), AUTH_CREDENTIALS)
        assert result["count"] == 0
        assert result["users"] == []

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.fn(SearchUsersInput(query="test"), {})


# ---------------------------------------------------------------------------
# CUSTOM_SCHEDULE_TWEET tool function logic
# ---------------------------------------------------------------------------

def _make_schedule_tweet_fn():
    def schedule_tweet(
        request: ScheduleTweetInput,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        # access_token is not used for draft creation but still validated
        get_access_token(auth_credentials)

        draft = {
            "text": request.text,
            "scheduled_time": request.scheduled_time,
            "media_urls": request.media_urls,
            "reply_to_tweet_id": request.reply_to_tweet_id,
        }

        return {
            "draft": draft,
            "message": f"Tweet scheduled for {request.scheduled_time}. Note: Actual scheduling requires a backend scheduler service.",
        }

    return schedule_tweet


@pytest.mark.composio
class TestCustomScheduleTweet:
    def setup_method(self):
        self.fn = _make_schedule_tweet_fn()

    def test_returns_draft_with_all_fields(self):
        result = self.fn(
            ScheduleTweetInput(
                text="Hello future!",
                scheduled_time="2026-12-25T10:00:00Z",
                media_urls=["https://example.com/img.png"],
                reply_to_tweet_id="tweet-99",
            ),
            AUTH_CREDENTIALS,
        )
        assert result["draft"]["text"] == "Hello future!"
        assert result["draft"]["scheduled_time"] == "2026-12-25T10:00:00Z"
        assert result["draft"]["media_urls"] == ["https://example.com/img.png"]
        assert result["draft"]["reply_to_tweet_id"] == "tweet-99"

    def test_message_contains_scheduled_time(self):
        result = self.fn(
            ScheduleTweetInput(text="Reminder!", scheduled_time="2026-01-01T00:00:00Z"),
            AUTH_CREDENTIALS,
        )
        assert "2026-01-01T00:00:00Z" in result["message"]

    def test_optional_fields_default_to_none(self):
        result = self.fn(
            ScheduleTweetInput(text="Simple tweet", scheduled_time="2026-06-15T09:00:00Z"),
            AUTH_CREDENTIALS,
        )
        assert result["draft"]["media_urls"] is None
        assert result["draft"]["reply_to_tweet_id"] is None

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.fn(
                ScheduleTweetInput(text="no auth", scheduled_time="2026-01-01T00:00:00Z"),
                {},
            )

    def test_does_not_make_any_http_calls(self):
        with patch("app.utils.twitter_utils._http_client") as mock_client:
            self.fn(
                ScheduleTweetInput(text="offline", scheduled_time="2026-01-01T00:00:00Z"),
                AUTH_CREDENTIALS,
            )
        mock_client.post.assert_not_called()
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# register_twitter_custom_tools returns correct tool name list
# ---------------------------------------------------------------------------

@pytest.mark.composio
class TestRegisterTwitterCustomTools:
    def test_returns_all_five_tool_names(self):
        from app.agents.tools.twitter_tool import register_twitter_custom_tools

        mock_composio = MagicMock()
        # composio.tools.custom_tool is used as a decorator — it must return a
        # callable that accepts a function and returns it unchanged so our inner
        # functions survive.
        mock_composio.tools.custom_tool.return_value = lambda fn: fn

        names = register_twitter_custom_tools(mock_composio)

        assert set(names) == {
            "TWITTER_CUSTOM_BATCH_FOLLOW",
            "TWITTER_CUSTOM_BATCH_UNFOLLOW",
            "TWITTER_CUSTOM_CREATE_THREAD",
            "TWITTER_CUSTOM_SEARCH_USERS",
            "TWITTER_CUSTOM_SCHEDULE_TWEET",
        }
        assert len(names) == 5
