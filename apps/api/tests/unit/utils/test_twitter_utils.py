"""Unit tests for Twitter API utility functions (proxy migration)."""

from unittest.mock import patch

import pytest

from app.models.integrations.twitter import TwitterCreatedTweet, TwitterUser
from app.services.composio.proxy_client import ProxyRequest
from app.utils.errors import AppError
from app.utils.twitter_utils import (
    TWITTER_API_BASE,
    TwitterOutcome,
    TwitterSearchOutcome,
    TwitterTweetOutcome,
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


_ME = {"data": {"id": "12345", "name": "Me", "username": "me"}}


class TestGetMyUserId:
    def test_returns_id_from_data(self, mock_proxy):
        mock_proxy.return_value = _ME
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
        mock_proxy.return_value = {"data": {"id": "1", "username": "elonmusk", "name": "Elon"}}
        result = lookup_user_by_username(USER_ID, "@elonmusk")
        assert result == TwitterUser(id="1", username="elonmusk", name="Elon")
        endpoint = mock_proxy.call_args.args[0].endpoint
        assert endpoint == f"{TWITTER_API_BASE}/users/by/username/elonmusk"

    def test_strips_only_leading_at_signs(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "2", "username": "Xavier", "name": "X"}}
        lookup_user_by_username(USER_ID, "@@Xavier")
        endpoint = mock_proxy.call_args.args[0].endpoint
        assert endpoint == f"{TWITTER_API_BASE}/users/by/username/Xavier"

    def test_unknown_handle_returns_none(self, mock_proxy):
        mock_proxy.return_value = {
            "errors": [{"detail": "Could not find user with username: [x]", "title": "Not Found"}]
        }
        assert lookup_user_by_username(USER_ID, "x") is None

    def test_returns_none_on_error(self, mock_proxy):
        mock_proxy.side_effect = Exception("boom")
        assert lookup_user_by_username(USER_ID, "x") is None


class TestFollowUser:
    def test_returns_success_on_ok(self, mock_proxy):
        mock_proxy.return_value = {"data": {"following": True}}
        result = follow_user(USER_ID, "me", "target")
        assert result == TwitterOutcome(success=True)
        request = mock_proxy.call_args.args[0]
        assert request.method == "POST"
        assert request.body == {"target_user_id": "target"}

    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(
            message="x", status_code=429, meta={"provider_response": {"title": "Too Many"}}
        )
        result = follow_user(USER_ID, "me", "target")
        assert result == TwitterOutcome(success=False, error="HTTP 429: {'title': 'Too Many'}")

    def test_returns_failure_on_other_error(self, mock_proxy):
        mock_proxy.side_effect = RuntimeError("boom")
        assert follow_user(USER_ID, "me", "target") == TwitterOutcome(success=False, error="boom")


class TestUnfollowUser:
    def test_sends_delete(self, mock_proxy):
        mock_proxy.return_value = {"data": {"following": False}}
        result = unfollow_user(USER_ID, "me", "target")
        assert result == TwitterOutcome(success=True)
        request = mock_proxy.call_args.args[0]
        assert request.method == "DELETE"
        assert request.endpoint.endswith("/users/me/following/target")


class TestUnfollowUserErrors:
    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="x", status_code=404)
        assert unfollow_user(USER_ID, "me", "target") == TwitterOutcome(
            success=False, error="HTTP 404: None"
        )

    def test_returns_failure_on_other_error(self, mock_proxy):
        mock_proxy.side_effect = RuntimeError("boom")
        assert unfollow_user(USER_ID, "me", "target") == TwitterOutcome(success=False, error="boom")


class TestCreateTweet:
    def test_basic_tweet(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1", "text": "hello"}}
        result = create_tweet(USER_ID, "hello")
        assert result == TwitterTweetOutcome(
            success=True, tweet=TwitterCreatedTweet(id="tw1", text="hello")
        )
        request = mock_proxy.call_args.args[0]
        assert request.method == "POST"
        assert request.body == {"text": "hello"}

    def test_reply(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1", "text": "reply"}}
        create_tweet(USER_ID, "reply", reply_to_tweet_id="parent")
        body = mock_proxy.call_args.args[0].body
        assert body["reply"] == {"in_reply_to_tweet_id": "parent"}

    def test_with_media_and_quote(self, mock_proxy):
        mock_proxy.return_value = {"data": {"id": "tw1", "text": "x"}}
        create_tweet(USER_ID, "x", media_ids=["m1"], quote_tweet_id="q1")
        body = mock_proxy.call_args.args[0].body
        assert body == {"text": "x", "media": {"media_ids": ["m1"]}, "quote_tweet_id": "q1"}

    def test_tweet_body_without_id_is_a_failure(self, mock_proxy):
        mock_proxy.return_value = {"data": {}}
        result = create_tweet(USER_ID, "x")
        assert result.success is False
        assert result.tweet is None
        assert "TwitterCreateTweetResponse" in (result.error or "")

    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="x", status_code=403)
        assert create_tweet(USER_ID, "x") == TwitterTweetOutcome(
            success=False, error="HTTP 403: None"
        )


class TestSearchTweets:
    def test_caps_max_results_at_100(self, mock_proxy):
        mock_proxy.return_value = {"data": []}
        result = search_tweets(USER_ID, "query", max_results=200)
        request = mock_proxy.call_args.args[0]
        assert request.query["max_results"] == 100
        assert result.success is True
        assert result.data is not None
        assert result.data.includes.users == []

    def test_returns_failure_on_app_error(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="x", status_code=500)
        result = search_tweets(USER_ID, "q")
        assert result == TwitterSearchOutcome(success=False, error="HTTP 500: None")

    def test_returns_failure_on_other_error(self, mock_proxy):
        mock_proxy.side_effect = RuntimeError("boom")
        assert search_tweets(USER_ID, "q") == TwitterSearchOutcome(success=False, error="boom")
