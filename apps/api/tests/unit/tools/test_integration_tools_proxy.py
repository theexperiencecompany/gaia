"""Smoke tests for integration tools after the Composio proxy migration.

Each integration tool registration is verified end-to-end:
1. Tools are registered under the expected names.
2. The tool body invokes `proxy_request_sync` with the right toolkit + endpoint.

Detailed per-function behavior tests live in the per-tool unit modules
(e.g. `test_composio_gmail_tools.py`). This file provides a regression net
that fails fast if a tool stops routing through the proxy.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.common_models import GatherContextInput
from app.models.google_docs_models import DeleteDocInput, ShareDocInput, ShareRecipient
from app.models.google_sheets_models import (
    ShareRecipient as SheetsRecipient,
    ShareSpreadsheetInput,
)
from app.models.linkedin_models import AddCommentInput, ReactToPostInput
from app.models.notion_models import FetchDataInput, MovePageInput
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
EXECUTE_REQUEST = MagicMock()


def _capture_tools(register_fn: Callable[..., Any]) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_fn(composio)
    return tools


# ---------------------------------------------------------------------------
# Reddit / Instagram / HubSpot / Microsoft Teams / Google Maps gather context
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path,register_name,toolkit,tool_name",
    [
        (
            "app.agents.tools.integrations.reddit_tool",
            "register_reddit_custom_tools",
            "REDDIT",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.instagram_tool",
            "register_instagram_custom_tools",
            "INSTAGRAM",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.hubspot_tool",
            "register_hubspot_custom_tools",
            "HUBSPOT",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.microsoft_teams_tool",
            "register_microsoft_teams_custom_tools",
            "MICROSOFT_TEAMS",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.google_maps_tool",
            "register_google_maps_custom_tools",
            "GOOGLE_MAPS",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.google_meet_tool",
            "register_google_meet_custom_tools",
            "GOOGLEMEET",
            "CUSTOM_GATHER_CONTEXT",
        ),
    ],
)
def test_gather_context_tools_use_proxy(
    module_path: str, register_name: str, toolkit: str, tool_name: str
) -> None:
    module = __import__(module_path, fromlist=[register_name])
    register = getattr(module, register_name)

    with patch(f"{module_path}.proxy_request_sync") as proxy:
        proxy.return_value = {}
        tools = _capture_tools(register)
        fn = tools[tool_name]
        fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert proxy.called
    first_call_kwargs = proxy.call_args_list[0].kwargs
    assert first_call_kwargs["toolkit"] == toolkit
    assert first_call_kwargs["user_id"] == AUTH_CREDS["user_id"]


# ---------------------------------------------------------------------------
# Google Docs
# ---------------------------------------------------------------------------


def test_google_meet_gather_context_swallows_calendar_failures() -> None:
    """If the GOOGLEMEET account lacks calendar scope, the events fetch raises.

    The tool must catch that and return an empty `upcoming_meets` list rather
    than failing the whole gather_context call.
    """
    from app.agents.tools.integrations.google_meet_tool import (
        register_google_meet_custom_tools,
    )
    from app.utils.errors import AppError

    with patch("app.agents.tools.integrations.google_meet_tool.proxy_request_sync") as proxy:
        # First call (userinfo) succeeds; second call (calendar/events) raises.
        proxy.side_effect = [
            {"email": "u@x.com", "name": "User", "picture": None},
            AppError(message="GOOGLEMEET API error (403)", status_code=403),
        ]
        tools = _capture_tools(register_google_meet_custom_tools)
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["email"] == "u@x.com"
    assert result["upcoming_meets"] == []
    assert result["upcoming_meet_count"] == 0


def test_google_docs_share_doc_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_docs_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"id": "perm-1"}
        tools = _capture_tools(register_google_docs_custom_tools)
        result = tools["CUSTOM_SHARE_DOC"](
            ShareDocInput(
                document_id="doc-1",
                recipients=[ShareRecipient(email="x@y.z", role="writer")],  # type: ignore[call-arg]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "GOOGLEDOCS"
    assert kwargs["method"] == "POST"
    assert "/permissions" in kwargs["endpoint"]
    assert result["document_id"] == "doc-1"


def test_google_docs_delete_doc_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_docs_tool.proxy_request_sync") as proxy:
        proxy.return_value = None
        tools = _capture_tools(register_google_docs_custom_tools)
        result = tools["CUSTOM_DELETE_DOC"](
            DeleteDocInput(document_id="doc-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["successful"] is True
    kwargs = proxy.call_args.kwargs
    assert kwargs["method"] == "DELETE"
    assert kwargs["endpoint"].endswith("/files/doc-1")


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------


def test_google_sheets_share_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_sheets_tool import (
        register_google_sheets_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_sheets_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"id": "perm-1"}
        tools = _capture_tools(register_google_sheets_custom_tools)
        result = tools["CUSTOM_SHARE_SPREADSHEET"](
            ShareSpreadsheetInput(
                spreadsheet_id="ss-1",
                recipients=[SheetsRecipient(email="x@y.z")],  # type: ignore[call-arg]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["total_shared"] == 1
    assert proxy.call_args.kwargs["toolkit"] == "GOOGLESHEETS"


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------


def test_notion_move_page_uses_execute_request_proxy() -> None:
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    tools = _capture_tools(register_notion_custom_tools)
    proxy_mock = MagicMock()
    proxy_mock.return_value.data = {"id": "page-1", "url": "https://notion.so/x"}
    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        proxy_mock,
        AUTH_CREDS,
    )
    proxy_mock.assert_called_once()
    assert result["page_id"] == "page-1"


def test_notion_fetch_data_routes_through_proxy() -> None:
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    with patch("app.agents.tools.integrations.notion_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools = _capture_tools(register_notion_custom_tools)
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", query="x"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "NOTION"
    assert kwargs["endpoint"].endswith("/search")


# ---------------------------------------------------------------------------
# Twitter
# ---------------------------------------------------------------------------


def test_twitter_batch_follow_uses_proxy_via_utils() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    with (
        patch(
            "app.agents.tools.integrations.twitter_tool.get_stream_writer",
            return_value=None,
        ),
        patch("app.utils.twitter_utils.proxy_request_sync") as proxy,
    ):
        # First call: get_my_user_id; second: lookup_user_by_username; third: follow
        proxy.side_effect = [
            {"data": {"id": "me"}},
            {"data": {"id": "u1", "username": "elon"}},
            {"data": {"following": True}},
        ]
        tools = _capture_tools(register_twitter_custom_tools)
        result = tools["CUSTOM_BATCH_FOLLOW"](
            BatchFollowInput(usernames=["elon"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["followed_count"] == 1


def test_twitter_create_thread_uses_proxy() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    with (
        patch(
            "app.agents.tools.integrations.twitter_tool.get_stream_writer",
            return_value=None,
        ),
        patch("app.utils.twitter_utils.proxy_request_sync") as utils_proxy,
        patch("app.agents.tools.integrations.twitter_tool.proxy_request_sync") as tool_proxy,
    ):
        utils_proxy.side_effect = [
            {"data": {"id": "tw1"}},
            {"data": {"id": "tw2"}},
        ]
        tool_proxy.return_value = {"data": {"username": "me"}}
        tools = _capture_tools(register_twitter_custom_tools)
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["tweet_count"] == 2


TWITTER_MODULE = "app.agents.tools.integrations.twitter_tool"
TWITTER_TOOL_NAMES = [
    "TWITTER_CUSTOM_BATCH_FOLLOW",
    "TWITTER_CUSTOM_BATCH_UNFOLLOW",
    "TWITTER_CUSTOM_CREATE_THREAD",
    "TWITTER_CUSTOM_SEARCH_USERS",
    "TWITTER_CUSTOM_SCHEDULE_TWEET",
    "TWITTER_CUSTOM_GATHER_CONTEXT",
]
TWITTER_BATCH_PARAMS = [
    pytest.param(
        "CUSTOM_BATCH_FOLLOW",
        BatchFollowInput,
        "follow_user",
        "followed_count",
        "Follow",
        "Failed to follow all users",
        id="follow",
    ),
    pytest.param(
        "CUSTOM_BATCH_UNFOLLOW",
        BatchUnfollowInput,
        "unfollow_user",
        "unfollowed_count",
        "Unfollow",
        "Failed to unfollow all users",
        id="unfollow",
    ),
]
TWITTER_REQUEST_PARAMS = [
    pytest.param("CUSTOM_BATCH_FOLLOW", BatchFollowInput(user_ids=["u1"]), id="batch-follow"),
    pytest.param("CUSTOM_BATCH_UNFOLLOW", BatchUnfollowInput(user_ids=["u1"]), id="batch-unfollow"),
    pytest.param("CUSTOM_CREATE_THREAD", CreateThreadInput(tweets=["a", "b"]), id="create-thread"),
    pytest.param("CUSTOM_SEARCH_USERS", SearchUsersInput(query="x"), id="search-users"),
    pytest.param(
        "CUSTOM_SCHEDULE_TWEET",
        ScheduleTweetInput(text="hi", scheduled_time="2025-01-01T00:00:00Z"),
        id="schedule-tweet",
    ),
    pytest.param("CUSTOM_GATHER_CONTEXT", GatherContextInput(), id="gather-context"),
]


def _twitter_tools() -> dict[str, Any]:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    return _capture_tools(register_twitter_custom_tools)


# --- registration -----------------------------------------------------------


def test_twitter_register_returns_expected_tool_names() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    assert register_twitter_custom_tools(MagicMock()) == TWITTER_TOOL_NAMES


def test_twitter_tools_registered_with_toolkit_and_docs() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )
    from app.templates.docstrings.twitter_tool_docs import (
        CUSTOM_BATCH_FOLLOW_DOC,
        CUSTOM_BATCH_UNFOLLOW_DOC,
        CUSTOM_CREATE_THREAD_DOC,
        CUSTOM_SCHEDULE_TWEET_DOC,
        CUSTOM_SEARCH_USERS_DOC,
    )

    registered: dict[str, tuple[str | None, Any]] = {}

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
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
        assert toolkit == "TWITTER"
    assert registered["CUSTOM_BATCH_FOLLOW"][1].__doc__ == CUSTOM_BATCH_FOLLOW_DOC
    assert registered["CUSTOM_BATCH_UNFOLLOW"][1].__doc__ == CUSTOM_BATCH_UNFOLLOW_DOC
    assert registered["CUSTOM_CREATE_THREAD"][1].__doc__ == CUSTOM_CREATE_THREAD_DOC
    assert registered["CUSTOM_SEARCH_USERS"][1].__doc__ == CUSTOM_SEARCH_USERS_DOC
    assert registered["CUSTOM_SCHEDULE_TWEET"][1].__doc__ == CUSTOM_SCHEDULE_TWEET_DOC


# --- _user_id ----------------------------------------------------------------


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_twitter_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    from app.agents.tools.integrations.twitter_tool import _user_id

    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


def test_twitter_user_id_returns_credentials_user_id() -> None:
    from app.agents.tools.integrations.twitter_tool import _user_id

    assert _user_id({"user_id": "user-1"}) == "user-1"


@pytest.mark.parametrize("tool_name,request_input", TWITTER_REQUEST_PARAMS)
def test_twitter_tools_reject_missing_user_id(tool_name: str, request_input: Any) -> None:
    tools = _twitter_tools()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        pytest.raises(ValueError) as excinfo,
    ):
        tools[tool_name](request_input, EXECUTE_REQUEST, {})
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


# --- CUSTOM_BATCH_FOLLOW / CUSTOM_BATCH_UNFOLLOW ------------------------------


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_rejects_unresolvable_my_user_id(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value=None),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Could not get authenticated user ID"
    util.assert_not_called()


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_rejects_empty_inputs(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
    ):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Either usernames or user_ids must be provided"


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_user_ids_only_succeeds_exactly(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id") as my_id,
        patch(f"{TWITTER_MODULE}.lookup_user_by_username") as lookup,
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": True, "data": {}},
            {"success": True, "data": {}},
        ]
        tools = _twitter_tools()
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
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_reports_individual_failures_with_errors(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": True, "data": {}},
            {"success": False, "error": "blocked"},
        ]
        tools = _twitter_tools()
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
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_resolves_usernames_and_reports_missing_ones(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username") as lookup,
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        lookup.side_effect = [
            {"id": "u1", "username": "elon", "name": "Elon"},
            None,
        ]
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
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
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_lookup_without_id_counts_as_not_found(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value={"username": "x"}),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(usernames=["x"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert fail_all_msg in str(excinfo.value)
    assert "User not found" in str(excinfo.value)


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_raises_when_all_operations_fail(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value=None),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(usernames=["ghost"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert fail_all_msg in str(excinfo.value)
    assert "User not found" in str(excinfo.value)


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_raises_when_every_lookup_fails(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value=None),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError, match=fail_all_msg):
            tools[tool_name](
                request_model(usernames=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_failure_results_carry_usernames(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(
            f"{TWITTER_MODULE}.lookup_user_by_username",
            return_value={"id": "u2", "username": "elon", "name": "Elon"},
        ),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": False, "error": "blocked"},
        ]
        tools = _twitter_tools()
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
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_reports_progress_every_five(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
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
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_is_silent_without_writer(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(user_ids=[f"u{i}" for i in range(6)]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result[count_key] == 6
    assert result["failed_count"] == 0


# --- CUSTOM_CREATE_THREAD -----------------------------------------------------


def test_twitter_create_thread_requires_two_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput.model_construct(tweets=["only"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Thread must have at least 2 tweets"


def test_twitter_create_thread_posts_thread_with_media() -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
            {"success": True, "data": {"id": "tw3"}},
        ]
        proxy.return_value = {"data": {"username": "me"}}
        tools = _twitter_tools()
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
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/users/me",
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


def test_twitter_create_thread_with_shorter_media_list() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(f"{TWITTER_MODULE}.proxy_request_sync", return_value=None),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _twitter_tools()
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


def test_twitter_create_thread_failure_reports_partial_tweet_ids() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": False, "error": "duplicate"},
        ]
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b", "c"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Failed at tweet 2: duplicate. Partial tweet IDs: ['tw1']"


def test_twitter_create_thread_failure_when_no_tweet_id_returned() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {}},
        ]
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "No ID returned for tweet 2. Partial tweet IDs: ['tw1']"


def test_twitter_create_thread_falls_back_to_generic_username_on_fetch_failure() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(
            f"{TWITTER_MODULE}.proxy_request_sync",
            side_effect=RuntimeError("api down"),
        ),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _twitter_tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["thread_url"] == "https://twitter.com/i/status/tw1"


# --- CUSTOM_SEARCH_USERS ------------------------------------------------------


def test_twitter_search_users_returns_capped_deduped_users() -> None:
    writer = MagicMock()
    long_desc = "d" * 200
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.search_tweets") as search,
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
        tools = _twitter_tools()
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


def test_twitter_search_users_raises_on_search_failure() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": False, "error": "api down"},
        ),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_SEARCH_USERS"](SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Search failed: api down"


def test_twitter_search_users_empty_includes_returns_no_users() -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": True, "data": {"includes": {}}},
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}
    assert writer.call_args_list == [call({"progress": "Searching for users matching: x..."})]


def test_twitter_search_users_skips_users_without_id() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={
                "success": True,
                "data": {"includes": {"users": [{"username": "ghost"}]}},
            },
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


def test_twitter_search_users_handles_data_without_includes() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": True, "data": {}},
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


# --- CUSTOM_SCHEDULE_TWEET ----------------------------------------------------


def test_twitter_schedule_tweet_builds_draft() -> None:
    writer = MagicMock()
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer):
        tools = _twitter_tools()
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
        "message": "Tweet scheduled for 2025-01-01T10:00:00Z. Note: Actual scheduling requires a backend scheduler service.",
    }
    writer.assert_called_once_with({"twitter_scheduled_draft": draft})


def test_twitter_schedule_tweet_without_writer_or_optional_fields() -> None:
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None):
        tools = _twitter_tools()
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


# --- CUSTOM_GATHER_CONTEXT ----------------------------------------------------


def test_twitter_gather_context_returns_profile_and_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy:
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
        tools = _twitter_tools()
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
            toolkit="TWITTER",
            endpoint="https://api.twitter.com/2/users/me",
            method="GET",
            query={"user.fields": "public_metrics,description,username"},
        ),
        call(
            user_id=AUTH_CREDS["user_id"],
            toolkit="TWITTER",
            endpoint="https://api.twitter.com/2/users/tid1/tweets",
            method="GET",
            query={"max_results": 5, "tweet.fields": "created_at,public_metrics"},
        ),
    ]


def test_twitter_gather_context_without_twitter_user_id_skips_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {}}
        tools = _twitter_tools()
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


def test_twitter_gather_context_logs_and_returns_partial_on_tweets_failure() -> None:
    from app.constants.log_tags import LogTag

    with (
        patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy,
        patch(f"{TWITTER_MODULE}.log.warning") as warn,
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
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] == "tid1"
    assert result["recent_tweets"] == []
    warn.assert_called_once_with(
        f"{LogTag.TOOL} Failed to fetch recent tweets, returning profile without them",
        twitter_user_id="tid1",
        error="api down",
        error_type="RuntimeError",
    )


def test_twitter_gather_context_handles_missing_proxy_response() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] is None
    assert result["user"]["description"] == ""
    assert result["recent_tweets"] == []
    proxy.assert_called_once()


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def test_linkedin_react_to_post_uses_proxy() -> None:
    from app.agents.tools.integrations.linkedin_tool import (
        register_linkedin_custom_tools,
    )

    with (
        patch("app.agents.tools.integrations.linkedin_tool.proxy_request_sync") as proxy,
        patch(
            "app.agents.tools.integrations.linkedin_tool.get_author_urn",
            return_value="urn:li:person:1",
        ),
    ):
        proxy.return_value = {}
        tools = _capture_tools(register_linkedin_custom_tools)
        result = tools["CUSTOM_REACT_TO_POST"](
            ReactToPostInput(post_urn="urn:li:share:1", reaction_type="LIKE"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["post_urn"] == "urn:li:share:1"
    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "LINKEDIN"
    assert kwargs["method"] == "POST"


def test_linkedin_add_comment_uses_proxy_full() -> None:
    from app.agents.tools.integrations.linkedin_tool import (
        register_linkedin_custom_tools,
    )

    with (
        patch("app.agents.tools.integrations.linkedin_tool.proxy_request_full_sync") as proxy_full,
        patch(
            "app.agents.tools.integrations.linkedin_tool.get_author_urn",
            return_value="urn:li:person:1",
        ),
    ):
        proxy_full.return_value = {
            "data": {"id": "comment-1"},
            "headers": {},
        }
        tools = _capture_tools(register_linkedin_custom_tools)
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn="urn:li:share:1", comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == "comment-1"
