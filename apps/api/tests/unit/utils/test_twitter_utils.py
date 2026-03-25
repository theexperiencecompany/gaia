"""Unit tests for Twitter API utility functions."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

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


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAccessToken:
    """Tests for extracting access tokens from auth_credentials dicts."""

    def test_returns_token_when_present(self) -> None:
        creds: Dict[str, Any] = {"access_token": "tok_abc123"}
        assert get_access_token(creds) == "tok_abc123"

    def test_raises_when_token_missing(self) -> None:
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({})

    def test_raises_when_token_is_none(self) -> None:
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": None})

    def test_raises_when_token_is_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": ""})

    def test_ignores_extra_fields(self) -> None:
        creds: Dict[str, Any] = {
            "access_token": "tok_xyz",
            "refresh_token": "ref_abc",
            "extra": 42,
        }
        assert get_access_token(creds) == "tok_xyz"


# ---------------------------------------------------------------------------
# twitter_headers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTwitterHeaders:
    """Tests for building Twitter API request headers."""

    def test_returns_bearer_auth_header(self) -> None:
        headers = twitter_headers("tok_abc")
        assert headers["Authorization"] == "Bearer tok_abc"

    def test_returns_json_content_type(self) -> None:
        headers = twitter_headers("tok_abc")
        assert headers["Content-Type"] == "application/json"

    def test_returns_exactly_two_keys(self) -> None:
        headers = twitter_headers("any_token")
        assert set(headers.keys()) == {"Authorization", "Content-Type"}


# ---------------------------------------------------------------------------
# get_my_user_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMyUserId:
    """Tests for fetching the authenticated user's ID."""

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_user_id_on_success(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"id": "12345"}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        result = get_my_user_id("tok_abc")
        assert result == "12345"
        mock_client.get.assert_called_once_with(
            f"{TWITTER_API_BASE}/users/me",
            headers=twitter_headers("tok_abc"),
        )

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_when_data_missing(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        assert get_my_user_id("tok_abc") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_when_id_missing_in_data(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"username": "alice"}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        assert get_my_user_id("tok_abc") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_on_http_error(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        mock_client.get.return_value = mock_resp

        assert get_my_user_id("tok_abc") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_on_generic_exception(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = Exception("network timeout")
        assert get_my_user_id("tok_abc") is None


# ---------------------------------------------------------------------------
# lookup_user_by_username
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLookupUserByUsername:
    """Tests for looking up a Twitter user by username."""

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_user_data_on_success(self, mock_client: MagicMock) -> None:
        user_data = {"id": "99", "name": "Alice", "username": "alice"}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": user_data}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        result = lookup_user_by_username("tok_abc", "alice")
        assert result == user_data

    @patch("app.utils.twitter_utils._http_client")
    def test_strips_at_symbol_from_username(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"id": "1"}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        lookup_user_by_username("tok_abc", "@alice")

        call_args = mock_client.get.call_args
        assert "/users/by/username/alice" in call_args[0][0]

    @patch("app.utils.twitter_utils._http_client")
    def test_strips_multiple_at_symbols(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"id": "1"}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        lookup_user_by_username("tok_abc", "@@alice")

        call_args = mock_client.get.call_args
        # lstrip("@") removes all leading @ symbols
        assert "/users/by/username/alice" in call_args[0][0]

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_when_data_key_absent(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errors": [{"message": "Not found"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        assert lookup_user_by_username("tok_abc", "nonexistent") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_on_http_error(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )
        mock_client.get.return_value = mock_resp

        assert lookup_user_by_username("tok_abc", "alice") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_none_on_generic_exception(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = ConnectionError("refused")
        assert lookup_user_by_username("tok_abc", "alice") is None

    @patch("app.utils.twitter_utils._http_client")
    def test_passes_user_fields_param(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"id": "1"}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        lookup_user_by_username("tok_abc", "alice")

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "user.fields" in params


# ---------------------------------------------------------------------------
# follow_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFollowUser:
    """Tests for the follow user endpoint."""

    @patch("app.utils.twitter_utils._http_client")
    def test_success_returns_data(self, mock_client: MagicMock) -> None:
        api_resp = {"data": {"following": True}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        result = follow_user("tok_abc", "my_id", "target_id")
        assert result["success"] is True
        assert result["data"] == api_resp

    @patch("app.utils.twitter_utils._http_client")
    def test_calls_correct_endpoint(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        follow_user("tok_abc", "uid_1", "uid_2")

        call_args = mock_client.post.call_args
        assert call_args[0][0] == f"{TWITTER_API_BASE}/users/uid_1/following"
        assert call_args.kwargs["json"] == {"target_user_id": "uid_2"}

    @patch("app.utils.twitter_utils._http_client")
    def test_http_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client.post.return_value = mock_resp

        result = follow_user("tok_abc", "uid_1", "uid_2")
        assert result["success"] is False
        assert "429" in result["error"]
        assert "Rate limit exceeded" in result["error"]

    @patch("app.utils.twitter_utils._http_client")
    def test_generic_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = Exception("connection reset")

        result = follow_user("tok_abc", "uid_1", "uid_2")
        assert result["success"] is False
        assert "connection reset" in result["error"]


# ---------------------------------------------------------------------------
# unfollow_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnfollowUser:
    """Tests for the unfollow user endpoint."""

    @patch("app.utils.twitter_utils._http_client")
    def test_success_returns_data(self, mock_client: MagicMock) -> None:
        api_resp = {"data": {"following": False}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client.delete.return_value = mock_resp

        result = unfollow_user("tok_abc", "my_id", "target_id")
        assert result["success"] is True
        assert result["data"] == api_resp

    @patch("app.utils.twitter_utils._http_client")
    def test_calls_correct_endpoint(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client.delete.return_value = mock_resp

        unfollow_user("tok_abc", "uid_1", "uid_2")

        call_args = mock_client.delete.call_args
        assert call_args[0][0] == f"{TWITTER_API_BASE}/users/uid_1/following/uid_2"

    @patch("app.utils.twitter_utils._http_client")
    def test_http_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client.delete.return_value = mock_resp

        result = unfollow_user("tok_abc", "uid_1", "uid_2")
        assert result["success"] is False
        assert "404" in result["error"]

    @patch("app.utils.twitter_utils._http_client")
    def test_generic_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.delete.side_effect = TimeoutError("timed out")

        result = unfollow_user("tok_abc", "uid_1", "uid_2")
        assert result["success"] is False
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# create_tweet
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateTweet:
    """Tests for creating tweets via the Twitter API v2."""

    @patch("app.utils.twitter_utils._http_client")
    def test_simple_tweet_success(self, mock_client: MagicMock) -> None:
        tweet_data = {"id": "t_123", "text": "Hello world"}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": tweet_data}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        result = create_tweet("tok_abc", "Hello world")
        assert result["success"] is True
        assert result["data"] == tweet_data

    @patch("app.utils.twitter_utils._http_client")
    def test_body_contains_only_text_by_default(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "test tweet")

        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body == {"text": "test tweet"}

    @patch("app.utils.twitter_utils._http_client")
    def test_reply_to_tweet_id_adds_reply_field(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "reply text", reply_to_tweet_id="t_original")

        body = mock_client.post.call_args.kwargs["json"]
        assert body["reply"] == {"in_reply_to_tweet_id": "t_original"}

    @patch("app.utils.twitter_utils._http_client")
    def test_media_ids_adds_media_field(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "photo!", media_ids=["m_1", "m_2"])

        body = mock_client.post.call_args.kwargs["json"]
        assert body["media"] == {"media_ids": ["m_1", "m_2"]}

    @patch("app.utils.twitter_utils._http_client")
    def test_quote_tweet_id_adds_field(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "qt!", quote_tweet_id="t_quoted")

        body = mock_client.post.call_args.kwargs["json"]
        assert body["quote_tweet_id"] == "t_quoted"

    @patch("app.utils.twitter_utils._http_client")
    def test_all_optional_fields_together(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet(
            "tok_abc",
            "full tweet",
            reply_to_tweet_id="t_reply",
            media_ids=["m_1"],
            quote_tweet_id="t_qt",
        )

        body = mock_client.post.call_args.kwargs["json"]
        assert body["text"] == "full tweet"
        assert body["reply"] == {"in_reply_to_tweet_id": "t_reply"}
        assert body["media"] == {"media_ids": ["m_1"]}
        assert body["quote_tweet_id"] == "t_qt"

    @patch("app.utils.twitter_utils._http_client")
    def test_no_reply_key_when_reply_to_tweet_id_is_none(
        self, mock_client: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "test")

        body = mock_client.post.call_args.kwargs["json"]
        assert "reply" not in body
        assert "media" not in body
        assert "quote_tweet_id" not in body

    @patch("app.utils.twitter_utils._http_client")
    def test_empty_media_ids_list_not_added(self, mock_client: MagicMock) -> None:
        """Empty list is falsy, so media field should not be added."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "test", media_ids=[])

        body = mock_client.post.call_args.kwargs["json"]
        assert "media" not in body

    @patch("app.utils.twitter_utils._http_client")
    def test_posts_to_tweets_endpoint(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        create_tweet("tok_abc", "test")

        assert mock_client.post.call_args[0][0] == f"{TWITTER_API_BASE}/tweets"

    @patch("app.utils.twitter_utils._http_client")
    def test_http_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client.post.return_value = mock_resp

        result = create_tweet("tok_abc", "test")
        assert result["success"] is False
        assert "403" in result["error"]

    @patch("app.utils.twitter_utils._http_client")
    def test_generic_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("unexpected")

        result = create_tweet("tok_abc", "test")
        assert result["success"] is False
        assert "unexpected" in result["error"]

    @patch("app.utils.twitter_utils._http_client")
    def test_returns_empty_dict_when_data_key_missing(
        self, mock_client: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        result = create_tweet("tok_abc", "test")
        assert result["success"] is True
        assert result["data"] == {}


# ---------------------------------------------------------------------------
# search_tweets
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchTweets:
    """Tests for the tweet search endpoint."""

    @patch("app.utils.twitter_utils._http_client")
    def test_success_returns_data(self, mock_client: MagicMock) -> None:
        api_data = {"data": [{"id": "1", "text": "match"}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_data
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        result = search_tweets("tok_abc", "python")
        assert result["success"] is True
        assert result["data"] == api_data

    @patch("app.utils.twitter_utils._http_client")
    def test_default_max_results_is_10(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        search_tweets("tok_abc", "test")

        params = mock_client.get.call_args.kwargs["params"]
        assert params["max_results"] == 10

    @patch("app.utils.twitter_utils._http_client")
    def test_max_results_capped_at_100(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        search_tweets("tok_abc", "test", max_results=500)

        params = mock_client.get.call_args.kwargs["params"]
        assert params["max_results"] == 100

    @pytest.mark.parametrize(
        "requested,expected",
        [
            (1, 1),
            (50, 50),
            (100, 100),
            (101, 100),
            (999, 100),
        ],
    )
    @patch("app.utils.twitter_utils._http_client")
    def test_max_results_clamping(
        self, mock_client: MagicMock, requested: int, expected: int
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        search_tweets("tok_abc", "q", max_results=requested)

        params = mock_client.get.call_args.kwargs["params"]
        assert params["max_results"] == expected

    @patch("app.utils.twitter_utils._http_client")
    def test_passes_query_and_expansions(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        search_tweets("tok_abc", "from:alice")

        params = mock_client.get.call_args.kwargs["params"]
        assert params["query"] == "from:alice"
        assert "author_id" in params["expansions"]

    @patch("app.utils.twitter_utils._http_client")
    def test_uses_search_recent_endpoint(self, mock_client: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        search_tweets("tok_abc", "test")

        assert (
            mock_client.get.call_args[0][0]
            == f"{TWITTER_API_BASE}/tweets/search/recent"
        )

    @patch("app.utils.twitter_utils._http_client")
    def test_http_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client.get.return_value = mock_resp

        result = search_tweets("tok_abc", "test")
        assert result["success"] is False
        assert "401" in result["error"]

    @patch("app.utils.twitter_utils._http_client")
    def test_generic_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = Exception("dns failure")

        result = search_tweets("tok_abc", "test")
        assert result["success"] is False
        assert "dns failure" in result["error"]
