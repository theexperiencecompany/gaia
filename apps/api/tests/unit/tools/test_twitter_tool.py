"""Unit tests for app.agents.tools.integrations.twitter_tool.

The Composio-registered custom tool bodies are exercised for real with only
the true I/O boundaries faked (`proxy_request_sync`, `get_stream_writer`,
and the `twitter_utils` helpers). Every test asserts the exact helper call
args (positional and keyword) and the exact returned dict or raised error
string, so a wrong constant, endpoint, default, or message fails loudly.
"""

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.twitter_tool import (
    _user_id,
    register_twitter_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)

MODULE = "app.agents.tools.integrations.twitter_tool"
AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
EXECUTE_REQUEST = MagicMock()

TWITTER_API_BASE = "https://api.twitter.com/2"
TWITTER_TOOLKIT = "TWITTER"

TOOL_NAMES = [
    "TWITTER_CUSTOM_BATCH_FOLLOW",
    "TWITTER_CUSTOM_BATCH_UNFOLLOW",
    "TWITTER_CUSTOM_CREATE_THREAD",
    "TWITTER_CUSTOM_SEARCH_USERS",
    "TWITTER_CUSTOM_SCHEDULE_TWEET",
    "TWITTER_CUSTOM_GATHER_CONTEXT",
]

BATCH_PARAMS = [
    pytest.param(
        "CUSTOM_BATCH_FOLLOW",
        BatchFollowInput,
        "follow_user",
        "Follow",
        "followed_count",
        "Failed to follow all users",
        id="follow",
    ),
    pytest.param(
        "CUSTOM_BATCH_UNFOLLOW",
        BatchUnfollowInput,
        "unfollow_user",
        "Unfollow",
        "unfollowed_count",
        "Failed to unfollow all users",
        id="unfollow",
    ),
]


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
    register_twitter_custom_tools(composio)
    return captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _tools()


# ---------------------------------------------------------------------------
# register_twitter_custom_tools
# ---------------------------------------------------------------------------


def test_register_returns_expected_tool_names() -> None:
    assert register_twitter_custom_tools(MagicMock()) == TOOL_NAMES


def test_register_wires_toolkit_and_docs() -> None:
    from app.templates.docstrings.twitter_tool_docs import (
        CUSTOM_BATCH_FOLLOW_DOC,
        CUSTOM_BATCH_UNFOLLOW_DOC,
        CUSTOM_CREATE_THREAD_DOC,
        CUSTOM_SCHEDULE_TWEET_DOC,
        CUSTOM_SEARCH_USERS_DOC,
    )

    registered: dict[str, tuple[str | None, Any]] = {}

    def custom_tool(**kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            registered[fn.__name__] = (kwargs.get("toolkit"), fn)
            return fn

        return decorator

    composio = MagicMock()
    composio.tools.custom_tool = custom_tool
    register_twitter_custom_tools(composio)

    assert set(registered) == {
        "CUSTOM_BATCH_FOLLOW",
        "CUSTOM_BATCH_UNFOLLOW",
        "CUSTOM_CREATE_THREAD",
        "CUSTOM_SEARCH_USERS",
        "CUSTOM_SCHEDULE_TWEET",
        "CUSTOM_GATHER_CONTEXT",
    }
    for toolkit, _fn in registered.values():
        assert toolkit == TWITTER_TOOLKIT
    assert registered["CUSTOM_BATCH_FOLLOW"][1].__doc__ == CUSTOM_BATCH_FOLLOW_DOC
    assert registered["CUSTOM_BATCH_UNFOLLOW"][1].__doc__ == CUSTOM_BATCH_UNFOLLOW_DOC
    assert registered["CUSTOM_CREATE_THREAD"][1].__doc__ == CUSTOM_CREATE_THREAD_DOC
    assert registered["CUSTOM_SEARCH_USERS"][1].__doc__ == CUSTOM_SEARCH_USERS_DOC
    assert registered["CUSTOM_SCHEDULE_TWEET"][1].__doc__ == CUSTOM_SCHEDULE_TWEET_DOC
    assert "Twitter/X context snapshot" in registered["CUSTOM_GATHER_CONTEXT"][1].__doc__


# ---------------------------------------------------------------------------
# _user_id
# ---------------------------------------------------------------------------


def test_user_id_returns_credentials_user_id() -> None:
    assert _user_id({"user_id": "user-1"}) == "user-1"


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


@pytest.mark.parametrize(
    "tool_name,request_input",
    [
        pytest.param("CUSTOM_BATCH_FOLLOW", BatchFollowInput(user_ids=["u1"]), id="batch-follow"),
        pytest.param(
            "CUSTOM_BATCH_UNFOLLOW", BatchUnfollowInput(user_ids=["u1"]), id="batch-unfollow"
        ),
        pytest.param(
            "CUSTOM_CREATE_THREAD", CreateThreadInput(tweets=["a", "b"]), id="create-thread"
        ),
        pytest.param("CUSTOM_SEARCH_USERS", SearchUsersInput(query="x"), id="search-users"),
        pytest.param(
            "CUSTOM_SCHEDULE_TWEET",
            ScheduleTweetInput(text="hi", scheduled_time="2025-01-01T00:00:00Z"),
            id="schedule-tweet",
        ),
        pytest.param("CUSTOM_GATHER_CONTEXT", GatherContextInput(), id="gather-context"),
    ],
)
def test_all_tools_reject_missing_user_id(tool_name: str, request_input: Any) -> None:
    tools = _tools()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        pytest.raises(ValueError) as excinfo,
    ):
        tools[tool_name](request_input, EXECUTE_REQUEST, {})
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


# ---------------------------------------------------------------------------
# CUSTOM_BATCH_FOLLOW / CUSTOM_BATCH_UNFOLLOW
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_rejects_unresolvable_my_user_id(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value=None),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        tools = _tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Could not get authenticated user ID"
    util.assert_not_called()


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_rejects_empty_inputs(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username"),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        tools = _tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Either usernames or user_ids must be provided"
    util.assert_not_called()


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_user_ids_only_succeeds_exactly(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id") as my_id,
        patch(f"{MODULE}.lookup_user_by_username") as lookup,
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": True, "data": {}},
            {"success": True, "data": {}},
        ]
        tools = _tools()
        result = tools[tool_name](
            request_model(user_ids=["u1", "u2"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"user_id": "u1", "username": None, "success": True},
            {"user_id": "u2", "username": None, "success": True},
        ],
        count_key: 2,
        "failed_count": 0,
    }
    my_id.assert_called_once_with(AUTH_CREDS["user_id"])
    lookup.assert_not_called()
    assert util.call_args_list == [
        call(AUTH_CREDS["user_id"], "my_id", "u1"),
        call(AUTH_CREDS["user_id"], "my_id", "u2"),
    ]
    assert writer.call_args_list == [call({"progress": f"{verb}ing 2 users..."})]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_reports_individual_failures_with_errors(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username"),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": True, "data": {}},
            {"success": False, "error": "blocked"},
        ]
        tools = _tools()
        result = tools[tool_name](
            request_model(user_ids=["u1", "u2", "u3"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"user_id": "u1", "username": None, "success": False, "error": "rate limited"},
            {"user_id": "u2", "username": None, "success": True},
            {"user_id": "u3", "username": None, "success": False, "error": "blocked"},
        ],
        count_key: 1,
        "failed_count": 2,
    }


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_resolves_usernames_and_reports_missing_ones(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username") as lookup,
        patch(f"{MODULE}.{util_name}") as util,
    ):
        lookup.side_effect = [
            {"id": "u1", "username": "elon", "name": "Elon"},
            None,
        ]
        util.return_value = {"success": True, "data": {}}
        tools = _tools()
        result = tools[tool_name](
            request_model(usernames=["elon", "ghost"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"username": "ghost", "success": False, "error": "User not found"},
            {"user_id": "u1", "username": "elon", "success": True},
        ],
        count_key: 1,
        "failed_count": 1,
    }
    assert lookup.call_args_list == [
        call(AUTH_CREDS["user_id"], "elon"),
        call(AUTH_CREDS["user_id"], "ghost"),
    ]
    util.assert_called_once_with(AUTH_CREDS["user_id"], "my_id", "u1")
    assert writer.call_args_list == [call({"progress": f"{verb}ing 1 users..."})]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_lookup_without_id_counts_as_not_found(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username", return_value={"username": "x"}),
    ):
        tools = _tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(usernames=["x"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == (
        f"{fail_all_msg}: [{{'username': 'x', 'success': False, 'error': 'User not found'}}]"
    )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_failure_results_carry_usernames(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(
            f"{MODULE}.lookup_user_by_username",
            return_value={"id": "u2", "username": "elon", "name": "Elon"},
        ),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": False, "error": "blocked"},
        ]
        tools = _tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(user_ids=["u1"], usernames=["elon"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == (
        f"{fail_all_msg}: "
        "[{'user_id': 'u1', 'username': None, 'success': False, 'error': 'rate limited'}, "
        "{'user_id': 'u2', 'username': 'elon', 'success': False, 'error': 'blocked'}]"
    )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_multiple_unresolved_usernames_accumulate_failures(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    # Two lookups miss (each must bump failed_count by 1) while a user_ids
    # follow succeeds — pins `failed_count += 1` accumulating per miss.
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username", return_value=None),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _tools()
        result = tools[tool_name](
            request_model(user_ids=["u1"], usernames=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"username": "a", "success": False, "error": "User not found"},
            {"username": "b", "success": False, "error": "User not found"},
            {"user_id": "u1", "username": None, "success": True},
        ],
        count_key: 1,
        "failed_count": 2,
    }


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_raises_when_every_lookup_fails(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username", return_value=None),
    ):
        tools = _tools()
        with pytest.raises(RuntimeError, match=fail_all_msg):
            tools[tool_name](
                request_model(usernames=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_reports_progress_every_five(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username"),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _tools()
        result = tools[tool_name](
            request_model(user_ids=[f"u{i}" for i in range(6)]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result[count_key] == 6
    assert result["failed_count"] == 0
    assert writer.call_args_list == [
        call({"progress": f"{verb}ing 6 users..."}),
        call({"progress": f"{verb}ed 5/6 users..."}),
    ]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,verb,count_key,fail_all_msg",
    BATCH_PARAMS,
)
def test_batch_is_silent_without_writer(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    verb: str,
    count_key: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{MODULE}.lookup_user_by_username"),
        patch(f"{MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _tools()
        result = tools[tool_name](
            request_model(user_ids=[f"u{i}" for i in range(6)]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result[count_key] == 6
    assert result["failed_count"] == 0


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_THREAD
# ---------------------------------------------------------------------------


def test_create_thread_requires_two_tweets() -> None:
    with patch(f"{MODULE}.get_stream_writer", return_value=None):
        tools = _tools()
        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput.model_construct(tweets=["only"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Thread must have at least 2 tweets"


def test_create_thread_posts_thread_with_media() -> None:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.create_tweet") as create_tweet,
        patch(f"{MODULE}.proxy_request_sync") as proxy,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
            {"success": True, "data": {"id": "tw3"}},
        ]
        proxy.return_value = {"data": {"username": "me"}}
        tools = _tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(
                tweets=["a", "b", "c"],
                media_ids=[["m1"], None, ["m3", "m4"]],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "thread_id": "tw1",
        "tweet_ids": ["tw1", "tw2", "tw3"],
        "tweet_count": 3,
        "thread_url": "https://twitter.com/me/status/tw1",
    }
    assert create_tweet.call_args_list == [
        call(AUTH_CREDS["user_id"], "a", reply_to_tweet_id=None, media_ids=["m1"]),
        call(AUTH_CREDS["user_id"], "b", reply_to_tweet_id="tw1", media_ids=None),
        call(AUTH_CREDS["user_id"], "c", reply_to_tweet_id="tw2", media_ids=["m3", "m4"]),
    ]
    proxy.assert_called_once_with(
        user_id=AUTH_CREDS["user_id"],
        toolkit=TWITTER_TOOLKIT,
        endpoint=f"{TWITTER_API_BASE}/users/me",
        method="GET",
    )
    assert writer.call_args_list == [
        call({"progress": "Creating thread with 3 tweets..."}),
        call({"progress": "Posted tweet 1/3..."}),
        call({"progress": "Posted tweet 2/3..."}),
        call({"progress": "Posted tweet 3/3..."}),
        call(
            {
                "twitter_thread_created": {
                    "thread_id": "tw1",
                    "tweet_count": 3,
                    "url": "https://twitter.com/me/status/tw1",
                }
            }
        ),
    ]


def test_create_thread_empty_media_entry_falls_back_to_none() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
        patch(f"{MODULE}.proxy_request_sync", return_value=None),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"], media_ids=[["m1"], []]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "thread_id": "tw1",
        "tweet_ids": ["tw1", "tw2"],
        "tweet_count": 2,
        "thread_url": "https://twitter.com/i/status/tw1",
    }
    assert create_tweet.call_args_list == [
        call(AUTH_CREDS["user_id"], "a", reply_to_tweet_id=None, media_ids=["m1"]),
        call(AUTH_CREDS["user_id"], "b", reply_to_tweet_id="tw1", media_ids=None),
    ]


def test_create_thread_with_shorter_media_list() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
        patch(f"{MODULE}.proxy_request_sync", return_value=None),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"], media_ids=[["m1"]]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "thread_id": "tw1",
        "tweet_ids": ["tw1", "tw2"],
        "tweet_count": 2,
        "thread_url": "https://twitter.com/i/status/tw1",
    }
    assert create_tweet.call_args_list == [
        call(AUTH_CREDS["user_id"], "a", reply_to_tweet_id=None, media_ids=["m1"]),
        call(AUTH_CREDS["user_id"], "b", reply_to_tweet_id="tw1", media_ids=None),
    ]


def test_create_thread_failure_reports_partial_tweet_ids() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": False, "error": "duplicate"},
        ]
        tools = _tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b", "c"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Failed at tweet 2: duplicate. Partial tweet IDs: ['tw1']"


def test_create_thread_failure_when_no_tweet_id_returned() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {}},
        ]
        tools = _tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "No ID returned for tweet 2. Partial tweet IDs: ['tw1']"


def test_create_thread_falls_back_to_generic_username_on_fetch_exception() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
        patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=RuntimeError("api down"),
        ),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["thread_url"] == "https://twitter.com/i/status/tw1"


def test_create_thread_falls_back_to_generic_username_on_empty_response() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(f"{MODULE}.create_tweet") as create_tweet,
        patch(f"{MODULE}.proxy_request_sync", return_value={}),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["thread_url"] == "https://twitter.com/i/status/tw1"


# ---------------------------------------------------------------------------
# CUSTOM_SEARCH_USERS
# ---------------------------------------------------------------------------


def test_search_users_returns_capped_deduped_users() -> None:
    writer = MagicMock()
    long_desc = "d" * 200
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.search_tweets") as search,
    ):
        search.return_value = {
            "success": True,
            "data": {
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "elonmusk",
                            "name": "Elon",
                            "description": long_desc,
                            "profile_image_url": "p1",
                            "verified": True,
                            "public_metrics": {"followers_count": 55},
                            "created_at": "2020-01-01",
                            "location": "TX",
                        },
                        {
                            "id": "u2",
                            "username": "barackobama",
                            "name": "Barack",
                            "profile_image_url": "p2",
                            "created_at": "2009-01-01",
                            "location": "DC",
                        },
                        {
                            "id": "u1",
                            "username": "elonmusk",
                            "name": "Elon",
                            "description": "duplicate",
                            "profile_image_url": "p1",
                            "verified": True,
                            "public_metrics": {"followers_count": 55},
                            "created_at": "2020-01-01",
                            "location": "TX",
                        },
                        {
                            "id": "u3",
                            "username": "billgates",
                            "name": "Bill",
                            "description": "short3",
                            "profile_image_url": "p3",
                            "verified": True,
                            "public_metrics": {"followers_count": 20},
                            "created_at": "2000-01-01",
                            "location": "WA",
                        },
                    ]
                }
            },
        }
        tools = _tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="elon", max_results=2),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "users": [
            {
                "id": "u1",
                "username": "elonmusk",
                "name": "Elon",
                "description": "d" * 150,
                "followers": 55,
                "verified": True,
            },
            {
                "id": "u2",
                "username": "barackobama",
                "name": "Barack",
                "description": "",
                "followers": 0,
                "verified": False,
            },
        ],
        "count": 2,
    }
    search.assert_called_once_with(AUTH_CREDS["user_id"], "elon -is:retweet", max_results=6)
    assert writer.call_args_list == [
        call({"progress": "Searching for users matching: elon..."}),
        call(
            {
                "twitter_user_data": [
                    {
                        "id": "u1",
                        "username": "elonmusk",
                        "name": "Elon",
                        "description": long_desc,
                        "profile_image_url": "p1",
                        "verified": True,
                        "public_metrics": {"followers_count": 55},
                        "created_at": "2020-01-01",
                        "location": "TX",
                    },
                    {
                        "id": "u2",
                        "username": "barackobama",
                        "name": "Barack",
                        "description": "",
                        "profile_image_url": "p2",
                        "verified": False,
                        "public_metrics": {},
                        "created_at": "2009-01-01",
                        "location": "DC",
                    },
                ]
            }
        ),
    ]


def test_search_users_raises_on_search_failure() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{MODULE}.search_tweets",
            return_value={"success": False, "error": "api down"},
        ),
    ):
        tools = _tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_SEARCH_USERS"](SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Search failed: api down"


def test_search_users_empty_includes_returns_no_users() -> None:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(
            f"{MODULE}.search_tweets",
            return_value={"success": True, "data": {"includes": {}}},
        ),
    ):
        tools = _tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}
    assert writer.call_args_list == [call({"progress": "Searching for users matching: x..."})]


def test_search_users_skips_users_without_id() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{MODULE}.search_tweets",
            return_value={
                "success": True,
                "data": {"includes": {"users": [{"username": "ghost"}]}},
            },
        ),
    ):
        tools = _tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


def test_search_users_handles_data_without_includes() -> None:
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{MODULE}.search_tweets",
            return_value={"success": True, "data": {}},
        ),
    ):
        tools = _tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


# ---------------------------------------------------------------------------
# CUSTOM_SCHEDULE_TWEET
# ---------------------------------------------------------------------------


def test_schedule_tweet_builds_draft() -> None:
    writer = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=writer):
        tools = _tools()
        result = tools["CUSTOM_SCHEDULE_TWEET"](
            ScheduleTweetInput(
                text="hello",
                scheduled_time="2025-01-01T10:00:00Z",
                media_urls=["m1"],
                reply_to_tweet_id="r1",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    draft = {
        "text": "hello",
        "scheduled_time": "2025-01-01T10:00:00Z",
        "media_urls": ["m1"],
        "reply_to_tweet_id": "r1",
    }
    assert result == {
        "draft": draft,
        "message": (
            "Tweet scheduled for 2025-01-01T10:00:00Z. "
            "Note: Actual scheduling requires a backend scheduler service."
        ),
    }
    writer.assert_called_once_with({"twitter_scheduled_draft": draft})


def test_schedule_tweet_without_writer_or_optional_fields() -> None:
    with patch(f"{MODULE}.get_stream_writer", return_value=None):
        tools = _tools()
        result = tools["CUSTOM_SCHEDULE_TWEET"](
            ScheduleTweetInput(text="hi", scheduled_time="2025-01-01T00:00:00Z"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
    assert result["draft"] == {
        "text": "hi",
        "scheduled_time": "2025-01-01T00:00:00Z",
        "media_urls": None,
        "reply_to_tweet_id": None,
    }
    assert result["message"] == (
        "Tweet scheduled for 2025-01-01T00:00:00Z. "
        "Note: Actual scheduling requires a backend scheduler service."
    )


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


def test_gather_context_returns_profile_and_tweets() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.side_effect = [
            {
                "data": {
                    "id": "tid1",
                    "username": "me",
                    "name": "Me",
                    "description": "d" * 300,
                    "public_metrics": {
                        "followers_count": 10,
                        "following_count": 5,
                        "tweet_count": 3,
                    },
                }
            },
            {
                "data": [
                    {
                        "id": "t1",
                        "text": "x" * 250,
                        "created_at": "c1",
                        "public_metrics": {"like_count": 7, "retweet_count": 2},
                    },
                    {"id": "t2"},
                ]
            },
        ]
        tools = _tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result == {
        "user": {
            "id": "tid1",
            "username": "me",
            "name": "Me",
            "description": "d" * 200,
            "followers": 10,
            "following": 5,
            "tweet_count": 3,
        },
        "recent_tweets": [
            {"id": "t1", "text": "x" * 200, "created_at": "c1", "likes": 7, "retweets": 2},
            {"id": "t2", "text": "", "created_at": None, "likes": 0, "retweets": 0},
        ],
    }
    assert proxy.call_args_list == [
        call(
            user_id=AUTH_CREDS["user_id"],
            toolkit=TWITTER_TOOLKIT,
            endpoint=f"{TWITTER_API_BASE}/users/me",
            method="GET",
            query={"user.fields": "public_metrics,description,username"},
        ),
        call(
            user_id=AUTH_CREDS["user_id"],
            toolkit=TWITTER_TOOLKIT,
            endpoint=f"{TWITTER_API_BASE}/users/tid1/tweets",
            method="GET",
            query={"max_results": 5, "tweet.fields": "created_at,public_metrics"},
        ),
    ]


def test_gather_context_without_twitter_user_id_skips_tweets() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {}}
        tools = _tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result == {
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
    assert proxy.call_count == 1


def test_gather_context_logs_and_returns_partial_on_tweets_failure() -> None:
    from app.constants.log_tags import LogTag

    with (
        patch(f"{MODULE}.proxy_request_sync") as proxy,
        patch(f"{MODULE}.log.warning") as warn,
    ):
        proxy.side_effect = [
            {
                "data": {
                    "id": "tid1",
                    "username": "me",
                    "name": "Me",
                    "description": "",
                    "public_metrics": {},
                }
            },
            RuntimeError("api down"),
        ]
        tools = _tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] == "tid1"
    assert result["recent_tweets"] == []
    warn.assert_called_once_with(
        f"{LogTag.TOOL} Failed to fetch recent tweets, returning profile without them",
        twitter_user_id="tid1",
        error="api down",
        error_type="RuntimeError",
    )


def test_gather_context_handles_missing_proxy_response() -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools = _tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] is None
    assert result["user"]["description"] == ""
    assert result["recent_tweets"] == []
    proxy.assert_called_once()


def test_gather_context_treats_non_list_tweets_data_as_empty() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.side_effect = [
            {"data": {"id": "tid1", "username": "me", "name": "Me", "public_metrics": {}}},
            {"data": {"not_a_list": True}},
        ]
        tools = _tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] == "tid1"
    assert result["recent_tweets"] == []
