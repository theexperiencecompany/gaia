"""Behavior tests for the Twitter custom tools.

The proxy smoke tests (test_integration_tools_proxy.py) prove the tools route
through proxy_request_sync; these pin the exact requests each tool sends and
what it does with the responses. The Twitter API helpers in
`app.utils.twitter_utils` run for real — the only seams faked are the two
`proxy_request_sync` boundaries (the tool's own and the utils') and the
LangGraph stream writer.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.twitter_tool import register_twitter_custom_tools
from app.models.common_models import GatherContextInput
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)
from app.services.composio.proxy_client import ProxyRequest
from app.utils.twitter_utils import TWITTER_API_BASE

MODULE = "app.agents.tools.integrations.twitter_tool"
UTILS_PROXY = "app.utils.twitter_utils.proxy_request_sync"
AUTH: dict[str, Any] = {"user_id": "user-42"}
EXECUTE_REQUEST = MagicMock()


def _tools() -> dict[str, Any]:
    """Register the Twitter custom tools against a fake Composio and capture them."""
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_twitter_custom_tools(composio)
    assert registered == [
        "TWITTER_CUSTOM_BATCH_FOLLOW",
        "TWITTER_CUSTOM_BATCH_UNFOLLOW",
        "TWITTER_CUSTOM_CREATE_THREAD",
        "TWITTER_CUSTOM_SEARCH_USERS",
        "TWITTER_CUSTOM_SCHEDULE_TWEET",
        "TWITTER_CUSTOM_GATHER_CONTEXT",
    ]
    return captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _tools()


@pytest.fixture
def writer():
    """Capture everything the tool pushes to the LangGraph stream."""
    sink = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=sink):
        yield sink


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------

_ME = {
    "data": {
        "id": "tw-me",
        "username": "ada",
        "name": "Ada Lovelace",
        "description": "d" * 300,
        "public_metrics": {"followers_count": 10, "following_count": 3, "tweet_count": 7},
    }
}

_TWEETS = {
    "data": [
        {
            "id": "t1",
            "text": "x" * 300,
            "created_at": "2026-01-01T00:00:00Z",
            "public_metrics": {"like_count": 2, "retweet_count": 1},
        },
        {"id": "t2", "text": "short"},
    ]
}


class TestGatherContext:
    def test_sends_profile_then_tweets_requests(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _TWEETS]) as proxy:
            tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)

        assert [c.args[0] for c in proxy.call_args_list] == [
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me",
                method="GET",
                query={"user.fields": "public_metrics,description,username"},
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/tw-me/tweets",
                method="GET",
                query={"max_results": 5, "tweet.fields": "created_at,public_metrics"},
            ),
        ]

    def test_returns_profile_and_truncated_recent_tweets(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _TWEETS]):
            out = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)

        assert out == {
            "user": {
                "id": "tw-me",
                "username": "ada",
                "name": "Ada Lovelace",
                "description": "d" * 200,
                "followers": 10,
                "following": 3,
                "tweet_count": 7,
            },
            "recent_tweets": [
                {
                    "id": "t1",
                    "text": "x" * 200,
                    "created_at": "2026-01-01T00:00:00Z",
                    "likes": 2,
                    "retweets": 1,
                },
                {"id": "t2", "text": "short", "created_at": None, "likes": 0, "retweets": 0},
            ],
        }

    def test_tweets_failure_keeps_profile(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, RuntimeError("rate")]):
            out = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)

        assert out["user"]["id"] == "tw-me"
        assert out["recent_tweets"] == []

    def test_no_profile_id_skips_tweets_request(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
            out = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)

        assert proxy.call_count == 1
        assert out == {
            "user": {
                "id": None,
                "username": None,
                "name": None,
                "description": "",
                "followers": 0,
                "following": 0,
                "tweet_count": 0,
            },
            "recent_tweets": [],
        }

    def test_non_list_tweet_payload_yields_no_tweets(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, {"data": {"id": "t1"}}]):
            out = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)

        assert out["recent_tweets"] == []

    @pytest.mark.parametrize("creds", [{}, {"user_id": ""}, {"user_id": 42}])
    def test_missing_user_id_raises(self, tools, creds) -> None:
        with patch(f"{MODULE}.proxy_request_sync") as proxy:
            with pytest.raises(ValueError, match="Missing user_id"):
                tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, creds)
        proxy.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_THREAD
# ---------------------------------------------------------------------------


class TestCreateThread:
    def test_chains_replies_and_resolves_username_for_url(self, tools, writer) -> None:
        with (
            patch(
                UTILS_PROXY, side_effect=[{"data": {"id": "tw1"}}, {"data": {"id": "tw2"}}]
            ) as utils_proxy,
            patch(
                f"{MODULE}.proxy_request_sync", return_value={"data": {"username": "ada"}}
            ) as tool_proxy,
        ):
            out = tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["first", "second"], media_ids=[["m1"], None]),
                EXECUTE_REQUEST,
                AUTH,
            )

        assert [c.args[0] for c in utils_proxy.call_args_list] == [
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/tweets",
                method="POST",
                body={"text": "first", "media": {"media_ids": ["m1"]}},
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/tweets",
                method="POST",
                body={"text": "second", "reply": {"in_reply_to_tweet_id": "tw1"}},
            ),
        ]
        assert [c.args[0] for c in tool_proxy.call_args_list] == [
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me",
                method="GET",
            )
        ]
        assert out == {
            "thread_id": "tw1",
            "tweet_ids": ["tw1", "tw2"],
            "tweet_count": 2,
            "thread_url": "https://twitter.com/ada/status/tw1",
        }
        writer.assert_any_call(
            {
                "twitter_thread_created": {
                    "thread_id": "tw1",
                    "tweet_count": 2,
                    "url": "https://twitter.com/ada/status/tw1",
                }
            }
        )

    def test_username_lookup_failure_falls_back_to_i(self, tools, writer) -> None:
        with (
            patch(UTILS_PROXY, side_effect=[{"data": {"id": "tw1"}}, {"data": {"id": "tw2"}}]),
            patch(f"{MODULE}.proxy_request_sync", side_effect=RuntimeError("down")),
        ):
            out = tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b"]), EXECUTE_REQUEST, AUTH
            )

        assert out["thread_url"] == "https://twitter.com/i/status/tw1"

    def test_empty_username_lookup_falls_back_to_i(self, tools, writer) -> None:
        with (
            patch(UTILS_PROXY, side_effect=[{"data": {"id": "tw1"}}, {"data": {"id": "tw2"}}]),
            patch(f"{MODULE}.proxy_request_sync", return_value=None),
        ):
            out = tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b"]), EXECUTE_REQUEST, AUTH
            )

        assert out["thread_url"] == "https://twitter.com/i/status/tw1"

    def test_failed_tweet_raises_with_partial_ids(self, tools, writer) -> None:
        with (
            patch(UTILS_PROXY, side_effect=[{"data": {"id": "tw1"}}, RuntimeError("boom")]),
            patch(f"{MODULE}.proxy_request_sync") as tool_proxy,
        ):
            with pytest.raises(
                RuntimeError, match=r"Failed at tweet 2: boom. Partial tweet IDs: \['tw1'\]"
            ):
                tools["CUSTOM_CREATE_THREAD"](
                    CreateThreadInput(tweets=["a", "b"]), EXECUTE_REQUEST, AUTH
                )
        tool_proxy.assert_not_called()

    def test_tweet_without_id_raises_with_partial_ids(self, tools, writer) -> None:
        with (
            patch(UTILS_PROXY, side_effect=[{"data": {"id": "tw1"}}, {"data": {}}]),
            patch(f"{MODULE}.proxy_request_sync"),
        ):
            with pytest.raises(
                RuntimeError, match=r"No ID returned for tweet 2. Partial tweet IDs: \['tw1'\]"
            ):
                tools["CUSTOM_CREATE_THREAD"](
                    CreateThreadInput(tweets=["a", "b"]), EXECUTE_REQUEST, AUTH
                )

    def test_fewer_than_two_tweets_raises(self, tools, writer) -> None:
        with patch(UTILS_PROXY) as utils_proxy:
            with pytest.raises(ValueError, match="at least 2 tweets"):
                tools["CUSTOM_CREATE_THREAD"](
                    CreateThreadInput.model_construct(tweets=["only"]), EXECUTE_REQUEST, AUTH
                )
        utils_proxy.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_BATCH_FOLLOW / CUSTOM_BATCH_UNFOLLOW
# ---------------------------------------------------------------------------


class TestBatchFollow:
    def test_follows_ids_and_resolved_usernames(self, tools, writer) -> None:
        with patch(
            UTILS_PROXY,
            side_effect=[
                {"data": {"id": "me"}},
                {"data": {"id": "u2", "username": "ada", "name": "Ada"}},
                {"data": {"following": True}},
                {"data": {"following": True}},
            ],
        ) as proxy:
            out = tools["CUSTOM_BATCH_FOLLOW"](
                BatchFollowInput(user_ids=["u1"], usernames=["@ada"]), EXECUTE_REQUEST, AUTH
            )

        assert [c.args[0] for c in proxy.call_args_list] == [
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me",
                method="GET",
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/by/username/ada",
                method="GET",
                query={
                    "user.fields": (
                        "id,name,username,description,profile_image_url,verified,public_metrics"
                    )
                },
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me/following",
                method="POST",
                body={"target_user_id": "u1"},
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me/following",
                method="POST",
                body={"target_user_id": "u2"},
            ),
        ]
        assert out == {
            "results": [
                {"user_id": "u1", "username": None, "success": True},
                {"user_id": "u2", "username": "ada", "success": True},
            ],
            "followed_count": 2,
            "failed_count": 0,
        }
        writer.assert_any_call({"progress": "Following 2 users..."})

    def test_unknown_username_is_reported_not_fatal(self, tools, writer) -> None:
        with patch(
            UTILS_PROXY,
            side_effect=[{"data": {"id": "me"}}, {}, {"data": {"following": True}}],
        ):
            out = tools["CUSTOM_BATCH_FOLLOW"](
                BatchFollowInput(user_ids=["u1"], usernames=["ghost"]), EXECUTE_REQUEST, AUTH
            )

        assert out == {
            "results": [
                {"username": "ghost", "success": False, "error": "User not found"},
                {"user_id": "u1", "username": None, "success": True},
            ],
            "followed_count": 1,
            "failed_count": 1,
        }

    def test_all_failures_raise(self, tools, writer) -> None:
        with patch(UTILS_PROXY, side_effect=[{"data": {"id": "me"}}, RuntimeError("nope")]):
            with pytest.raises(RuntimeError, match="Failed to follow all users"):
                tools["CUSTOM_BATCH_FOLLOW"](
                    BatchFollowInput(user_ids=["u1"]), EXECUTE_REQUEST, AUTH
                )

    def test_no_targets_raises(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value={"data": {"id": "me"}}):
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                tools["CUSTOM_BATCH_FOLLOW"](BatchFollowInput(), EXECUTE_REQUEST, AUTH)

    def test_unresolvable_self_id_raises(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value={}):
            with pytest.raises(ValueError, match="Could not get authenticated user ID"):
                tools["CUSTOM_BATCH_FOLLOW"](
                    BatchFollowInput(user_ids=["u1"]), EXECUTE_REQUEST, AUTH
                )

    def test_progress_is_streamed_every_five_users(self, tools, writer) -> None:
        with patch(
            UTILS_PROXY,
            side_effect=[{"data": {"id": "me"}}] + [{"data": {"following": True}}] * 6,
        ):
            tools["CUSTOM_BATCH_FOLLOW"](
                BatchFollowInput(user_ids=[f"u{i}" for i in range(6)]), EXECUTE_REQUEST, AUTH
            )

        assert [c.args[0] for c in writer.call_args_list] == [
            {"progress": "Following 6 users..."},
            {"progress": "Followed 5/6 users..."},
        ]


class TestBatchUnfollow:
    def test_unfollows_ids_and_resolved_usernames(self, tools, writer) -> None:
        with patch(
            UTILS_PROXY,
            side_effect=[
                {"data": {"id": "me"}},
                {"data": {"id": "u2", "username": "ada"}},
                {"data": {"following": False}},
                {"data": {"following": False}},
            ],
        ) as proxy:
            out = tools["CUSTOM_BATCH_UNFOLLOW"](
                BatchUnfollowInput(user_ids=["u1"], usernames=["ada"]), EXECUTE_REQUEST, AUTH
            )

        assert [c.args[0] for c in proxy.call_args_list[2:]] == [
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me/following/u1",
                method="DELETE",
            ),
            ProxyRequest(
                user_id="user-42",
                toolkit="TWITTER",
                endpoint=f"{TWITTER_API_BASE}/users/me/following/u2",
                method="DELETE",
            ),
        ]
        assert out == {
            "results": [
                {"user_id": "u1", "username": None, "success": True},
                {"user_id": "u2", "username": "ada", "success": True},
            ],
            "unfollowed_count": 2,
            "failed_count": 0,
        }
        writer.assert_any_call({"progress": "Unfollowing 2 users..."})

    def test_partial_failure_is_reported(self, tools, writer) -> None:
        with patch(
            UTILS_PROXY,
            side_effect=[{"data": {"id": "me"}}, RuntimeError("nope"), {"data": {}}],
        ):
            out = tools["CUSTOM_BATCH_UNFOLLOW"](
                BatchUnfollowInput(user_ids=["u1", "u2"]), EXECUTE_REQUEST, AUTH
            )

        assert out == {
            "results": [
                {"user_id": "u1", "username": None, "success": False, "error": "nope"},
                {"user_id": "u2", "username": None, "success": True},
            ],
            "unfollowed_count": 1,
            "failed_count": 1,
        }

    def test_all_failures_raise(self, tools, writer) -> None:
        with patch(UTILS_PROXY, side_effect=[{"data": {"id": "me"}}, {}]):
            with pytest.raises(RuntimeError, match="Failed to unfollow all users"):
                tools["CUSTOM_BATCH_UNFOLLOW"](
                    BatchUnfollowInput(usernames=["ghost"]), EXECUTE_REQUEST, AUTH
                )

    def test_no_targets_raises(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value={"data": {"id": "me"}}):
            with pytest.raises(ValueError, match="Either usernames or user_ids"):
                tools["CUSTOM_BATCH_UNFOLLOW"](BatchUnfollowInput(), EXECUTE_REQUEST, AUTH)

    def test_progress_is_streamed_every_five_users(self, tools, writer) -> None:
        with patch(UTILS_PROXY, side_effect=[{"data": {"id": "me"}}] + [{}] * 5):
            tools["CUSTOM_BATCH_UNFOLLOW"](
                BatchUnfollowInput(user_ids=[f"u{i}" for i in range(5)]), EXECUTE_REQUEST, AUTH
            )

        assert [c.args[0] for c in writer.call_args_list] == [
            {"progress": "Unfollowing 5 users..."},
            {"progress": "Unfollowed 5/5 users..."},
        ]


# ---------------------------------------------------------------------------
# CUSTOM_SEARCH_USERS
# ---------------------------------------------------------------------------

_SEARCH = {
    "data": [],
    "includes": {
        "users": [
            {
                "id": "u1",
                "username": "ada",
                "name": "Ada",
                "description": "b" * 200,
                "verified": True,
                "public_metrics": {"followers_count": 99},
            },
            {"id": "u1", "username": "dup"},
            {"id": "u2", "username": "bob"},
            {"username": "no-id"},
            {"id": "u3", "username": "carol"},
        ]
    },
}


class TestSearchUsers:
    def test_searches_recent_tweets_with_expanded_authors(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value=_SEARCH) as proxy:
            tools["CUSTOM_SEARCH_USERS"](
                SearchUsersInput(query="ada", max_results=2), EXECUTE_REQUEST, AUTH
            )

        assert proxy.call_args.args[0] == ProxyRequest(
            user_id="user-42",
            toolkit="TWITTER",
            endpoint=f"{TWITTER_API_BASE}/tweets/search/recent",
            method="GET",
            query={
                "query": "ada -is:retweet",
                "max_results": 6,
                "user.fields": (
                    "id,name,username,description,profile_image_url,verified,"
                    "public_metrics,created_at,location"
                ),
                "expansions": "author_id",
            },
        )
        writer.assert_any_call({"progress": "Searching for users matching: ada..."})

    def test_dedupes_authors_and_caps_at_max_results(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value=_SEARCH):
            out = tools["CUSTOM_SEARCH_USERS"](
                SearchUsersInput(query="ada", max_results=2), EXECUTE_REQUEST, AUTH
            )

        assert out == {
            "users": [
                {
                    "id": "u1",
                    "username": "ada",
                    "name": "Ada",
                    "description": "b" * 150,
                    "followers": 99,
                    "verified": True,
                },
                {
                    "id": "u2",
                    "username": "bob",
                    "name": None,
                    "description": "",
                    "followers": 0,
                    "verified": False,
                },
            ],
            "count": 2,
        }
        streamed = writer.call_args_list[-1].args[0]["twitter_user_data"]
        assert [u["id"] for u in streamed] == ["u1", "u2"]
        assert streamed[0] == {
            "id": "u1",
            "username": "ada",
            "name": "Ada",
            "description": "b" * 200,
            "profile_image_url": None,
            "verified": True,
            "public_metrics": {"followers_count": 99},
            "created_at": None,
            "location": None,
        }

    def test_no_matches_streams_nothing_extra(self, tools, writer) -> None:
        with patch(UTILS_PROXY, return_value={"data": []}):
            out = tools["CUSTOM_SEARCH_USERS"](
                SearchUsersInput(query="nobody"), EXECUTE_REQUEST, AUTH
            )

        assert out == {"users": [], "count": 0}
        assert [c.args[0] for c in writer.call_args_list] == [
            {"progress": "Searching for users matching: nobody..."}
        ]

    def test_search_failure_raises(self, tools, writer) -> None:
        with patch(UTILS_PROXY, side_effect=RuntimeError("throttled")):
            with pytest.raises(RuntimeError, match="Search failed: throttled"):
                tools["CUSTOM_SEARCH_USERS"](SearchUsersInput(query="ada"), EXECUTE_REQUEST, AUTH)


# ---------------------------------------------------------------------------
# CUSTOM_SCHEDULE_TWEET
# ---------------------------------------------------------------------------


class TestScheduleTweet:
    def test_returns_and_streams_the_draft(self, tools, writer) -> None:
        out = tools["CUSTOM_SCHEDULE_TWEET"](
            ScheduleTweetInput(
                text="hello",
                scheduled_time="2026-12-25T10:00:00Z",
                media_urls=["https://x/img.png"],
                reply_to_tweet_id="tw0",
            ),
            EXECUTE_REQUEST,
            AUTH,
        )

        draft = {
            "text": "hello",
            "scheduled_time": "2026-12-25T10:00:00Z",
            "media_urls": ["https://x/img.png"],
            "reply_to_tweet_id": "tw0",
        }
        assert out == {
            "draft": draft,
            "message": (
                "Tweet scheduled for 2026-12-25T10:00:00Z. "
                "Note: Actual scheduling requires a backend scheduler service."
            ),
        }
        writer.assert_called_once_with({"twitter_scheduled_draft": draft})

    def test_missing_user_id_raises(self, tools, writer) -> None:
        with pytest.raises(ValueError, match="Missing user_id"):
            tools["CUSTOM_SCHEDULE_TWEET"](
                ScheduleTweetInput(text="hi", scheduled_time="2026-12-25T10:00:00Z"),
                EXECUTE_REQUEST,
                {},
            )
