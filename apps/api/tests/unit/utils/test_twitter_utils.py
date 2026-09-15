"""Unit tests for Twitter API utility functions (proxy migration)."""

from unittest.mock import patch

import pytest

from app.services.composio.proxy_client import ProxyRequest
from app.utils.errors import AppError
from app.utils.twitter_utils import (
    TWITTER_API_BASE,
    create_tweet,
    follow_user,
    get_my_user_id,
    lookup_user_by_username,
    search_tweets,
    unfollow_user,
)

USER_ID = "user_test_123"
PROXY_PATH = "app.utils.twitter_utils.proxy_request_sync"


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {}
        yield proxy


class TestGetMyUserId:
    def test_returns_id_from_data(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "12345"}}
        assert get_my_user_id(USER_ID) == "12345"
        assert mock_proxy.call_args.args[0] == ProxyRequest(
            user_id=USER_ID,
            toolkit="TWITTER",
            endpoint=f"{TWITTER_API_BASE}/users/me",
            method="GET",
        )

    def test_returns_none_on_missing_data(self, mock_proxy):
        mock_proxy.return_value = {}
        assert get_my_user_id(USER_ID) is None

    def test_returns_none_on_error(self, mock_proxy):
        mock_proxy.side_effect = Exception("boom")
        assert get_my_user_id(USER_ID) is None


class TestLookupUserByUsername:
    def test_strips_at_and_returns_data(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "1", "username": "elonmusk"}}
        result = lookup_user_by_username(USER_ID, "@elonmusk")
        assert result == {"id": "1", "username": "elonmusk"}
        endpoint = mock_proxy.call_args.args[0].endpoint
        assert endpoint == f"{TWITTER_API_BASE}/users/by/username/elonmusk"

    def test_returns_none_on_error(self, mock_proxy):
        mock_proxy.side_effect = Exception("boom")
        assert lookup_user_by_username(USER_ID, "x") is None


class TestFollowUser:
    def test_returns_success_on_ok(self, mock_proxy):
        mock_proxy.return_value = {"data": {"following": True}}
        result = follow_user(USER_ID, "me", "target")
        assert result["success"] is True
        request = mock_proxy.call_args.args[0]
        assert request.method == "POST"
        assert request.body == {"target_user_id": "target"}

    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="x", status_code=429)
        result = follow_user(USER_ID, "me", "target")
        assert result["success"] is False
        assert "429" in result["error"]


class TestUnfollowUser:
    def test_sends_delete(self, mock_proxy):
        mock_proxy.return_value = {"data": {"following": False}}
        result = unfollow_user(USER_ID, "me", "target")
        assert result["success"] is True
        request = mock_proxy.call_args.args[0]
        assert request.method == "DELETE"
        assert request.endpoint.endswith("/users/me/following/target")


class TestCreateTweet:
    def test_basic_tweet(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1"}}
        result = create_tweet(USER_ID, "hello")
        assert result["success"] is True
        request = mock_proxy.call_args.args[0]
        assert request.method == "POST"
        assert request.body == {"text": "hello"}

    def test_reply(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1"}}
        create_tweet(USER_ID, "reply", reply_to_tweet_id="parent")
        body = mock_proxy.call_args.args[0].body
        assert body["reply"] == {"in_reply_to_tweet_id": "parent"}

    def test_with_media_and_quote(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1"}}
        create_tweet(USER_ID, "x", media_ids=["m1"], quote_tweet_id="q1")
        body = mock_proxy.call_args.args[0].body
        assert body["media"] == {"media_ids": ["m1"]}
        assert body["quote_tweet_id"] == "q1"


class TestSearchTweets:
    def test_caps_max_results_at_100(self, mock_proxy):
        mock_proxy.return_value = {"data": []}
        search_tweets(USER_ID, "query", max_results=200)
        request = mock_proxy.call_args.args[0]
        assert request.query["max_results"] == 100

    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="x", status_code=500)
        result = search_tweets(USER_ID, "q")
        assert result["success"] is False
