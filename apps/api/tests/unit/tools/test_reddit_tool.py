"""Unit tests for app.agents.tools.integrations.reddit_tool.

Only the true I/O boundaries are faked: `proxy_request_sync` (routed through a
canned Reddit API fake that records every request) and the wide-event logger.
Everything else — request assembly, defaults, 80-char truncation, graceful
degradation — runs for real, so the assertions pin the exact payloads the tool
produces and the exact requests it sends.

The registration smoke test for this module also lives in
`test_integration_tools_proxy.py`; this file is the per-tool behavioral net.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.reddit_tool import (
    REDDIT_API_BASE,
    REDDIT_TOOLKIT,
    register_reddit_custom_tools,
)
from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.reddit_tool"
USER_ID = "user-42"
AUTH_CREDS: dict[str, Any] = {"user_id": USER_ID}
EXECUTE_REQUEST = MagicMock()
USER_AGENT = {"User-Agent": "GAIA/1.0"}

ME_ENDPOINT = f"{REDDIT_API_BASE}/api/v1/me"
SUBS_ENDPOINT = f"{REDDIT_API_BASE}/subreddits/mine/subscriber"
MESSAGES_ENDPOINT = f"{REDDIT_API_BASE}/message/unread"

ME_ERROR_LOG = f"{LogTag.TOOL} Reddit /me fetch failed"
SUBS_ERROR_LOG = f"{LogTag.TOOL} Reddit subreddits fetch failed"
MESSAGES_ERROR_LOG = f"{LogTag.TOOL} Reddit unread messages fetch failed"

DEFAULT_USER = {
    "name": None,
    "id": None,
    "link_karma": 0,
    "comment_karma": 0,
    "total_karma": 0,
    "icon_img": None,
    "is_gold": False,
}


class FakeRedditApi:
    """Routes proxy calls to canned Reddit responses and records every request."""

    def __init__(self) -> None:
        self.me: Any = {}
        self.subs: Any = {}
        self.messages: Any = {}
        self.me_error: Exception | None = None
        self.subs_error: Exception | None = None
        self.messages_error: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs["endpoint"] == ME_ENDPOINT:
            if self.me_error is not None:
                raise self.me_error
            return self.me
        if kwargs["endpoint"] == SUBS_ENDPOINT:
            if self.subs_error is not None:
                raise self.subs_error
            return self.subs
        if kwargs["endpoint"] == MESSAGES_ENDPOINT:
            if self.messages_error is not None:
                raise self.messages_error
            return self.messages
        raise AssertionError(f"unexpected endpoint: {kwargs['endpoint']}")


def _register() -> tuple[list[str], dict[str, Any]]:
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    names = register_reddit_custom_tools(composio)
    return names, captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _register()[1]


@pytest.fixture
def api() -> FakeRedditApi:
    fake = FakeRedditApi()
    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=fake),
        patch(f"{MODULE}.log") as logger,
    ):
        fake.log = logger
        yield fake


def _call(tools: dict[str, Any], credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = tools["CUSTOM_GATHER_CONTEXT"](
        GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS if credentials is None else credentials
    )
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_returns_the_single_advertised_tool_name(self) -> None:
        names, captured = _register()

        # A name in the list with no tool behind it is a tool the agent can
        # select and never execute.
        assert names == ["REDDIT_CUSTOM_GATHER_CONTEXT"]
        assert names == [f"REDDIT_{fn}" for fn in captured]

    def test_tool_is_registered_under_the_reddit_toolkit(self) -> None:
        composio = MagicMock()
        register_reddit_custom_tools(composio)

        composio.tools.custom_tool.assert_called_once_with(toolkit=REDDIT_TOOLKIT)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


class TestMissingUserId:
    @pytest.mark.parametrize(
        "credentials",
        [{}, {"user_id": None}, {"user_id": ""}, {"user_id": 0}, {"userId": "abc"}],
    )
    def test_unusable_credentials_raise_app_error_before_any_proxy_call(
        self, tools: Any, api: FakeRedditApi, credentials: dict[str, Any]
    ) -> None:
        with pytest.raises(AppError) as excinfo:
            _call(tools, credentials)

        assert excinfo.value.message == "Missing user_id in auth_credentials"
        assert excinfo.value.why == "CUSTOM_GATHER_CONTEXT requires a user-scoped auth context"
        assert excinfo.value.status_code == 500
        # Falling through with a blank user id would send the request as nobody.
        assert api.calls == []


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestGatherContextSuccess:
    def test_returns_the_full_snapshot(self, tools: Any, api: FakeRedditApi) -> None:
        api.me = {
            "name": "gaia_user",
            "id": "u1",
            "link_karma": 10,
            "comment_karma": 20,
            "total_karma": 30,
            "icon_img": "https://i.redd.it/avatar.png",
            "is_gold": True,
        }
        api.subs = {
            "data": {
                "children": [
                    {"data": {"display_name": "r/python", "title": "Python", "subscribers": 1_200_000}},
                    {"data": {"display_name": "r/gaia", "title": "GAIA community", "subscribers": 42}},
                ]
            }
        }
        api.messages = {
            "data": {
                "children": [
                    {"data": {"id": "m1", "subject": "Hello", "author": "alice", "created_utc": 1_700_000_000}},
                    {"data": {"id": "m2", "subject": "Re: Hello", "author": "bob", "created_utc": 1_700_000_001}},
                ]
            }
        }

        result = _call(tools)

        assert result == {
            "user": {
                "name": "gaia_user",
                "id": "u1",
                "link_karma": 10,
                "comment_karma": 20,
                "total_karma": 30,
                "icon_img": "https://i.redd.it/avatar.png",
                "is_gold": True,
            },
            "subscribed_subreddits": [
                {"name": "r/python", "title": "Python", "subscribers": 1_200_000},
                {"name": "r/gaia", "title": "GAIA community", "subscribers": 42},
            ],
            "unread_messages": [
                {"id": "m1", "subject": "Hello", "author": "alice", "created_utc": 1_700_000_000},
                {"id": "m2", "subject": "Re: Hello", "author": "bob", "created_utc": 1_700_000_001},
            ],
            "unread_message_count": 2,
        }
        # A clean snapshot must not log any failure.
        api.log.set.assert_not_called()
        api.log.error.assert_not_called()

    def test_sends_exactly_three_proxy_requests_in_order(
        self, tools: Any, api: FakeRedditApi
    ) -> None:
        _call(tools)

        assert len(api.calls) == 3
        assert api.calls[0] == {
            "user_id": USER_ID,
            "toolkit": REDDIT_TOOLKIT,
            "endpoint": ME_ENDPOINT,
            "method": "GET",
            "headers": USER_AGENT,
        }
        assert api.calls[1] == {
            "user_id": USER_ID,
            "toolkit": REDDIT_TOOLKIT,
            "endpoint": SUBS_ENDPOINT,
            "method": "GET",
            "query": {"limit": 5},
            "headers": USER_AGENT,
        }
        assert api.calls[2] == {
            "user_id": USER_ID,
            "toolkit": REDDIT_TOOLKIT,
            "endpoint": MESSAGES_ENDPOINT,
            "method": "GET",
            "query": {"limit": 5},
            "headers": USER_AGENT,
        }


# ---------------------------------------------------------------------------
# Missing optional fields -> defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_me_fields_fall_back_to_none_and_zero(self, tools: Any, api: FakeRedditApi) -> None:
        api.me = {"name": "only_name"}

        result = _call(tools)

        assert result["user"] == {
            "name": "only_name",
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        }
        api.log.error.assert_not_called()

    def test_subreddit_without_title_or_subscribers(self, tools: Any, api: FakeRedditApi) -> None:
        api.subs = {"data": {"children": [{"data": {"display_name": "r/x"}}]}}

        result = _call(tools)

        assert result["subscribed_subreddits"] == [{"name": "r/x", "title": "", "subscribers": 0}]
        api.log.error.assert_not_called()

    def test_subreddit_title_is_truncated_to_80_chars(self, tools: Any, api: FakeRedditApi) -> None:
        api.subs = {
            "data": {"children": [{"data": {"display_name": "r/x", "title": "x" * 200, "subscribers": 1}}]}
        }

        result = _call(tools)

        assert result["subscribed_subreddits"][0]["title"] == "x" * 80

    def test_message_without_optional_fields(self, tools: Any, api: FakeRedditApi) -> None:
        api.messages = {"data": {"children": [{"data": {"id": "m9"}}]}}

        result = _call(tools)

        assert result["unread_messages"] == [
            {"id": "m9", "subject": "", "author": None, "created_utc": None}
        ]
        assert result["unread_message_count"] == 1
        api.log.error.assert_not_called()

    def test_message_subject_is_truncated_to_80_chars(self, tools: Any, api: FakeRedditApi) -> None:
        api.messages = {"data": {"children": [{"data": {"subject": "y" * 150}}]}}

        result = _call(tools)

        assert result["unread_messages"][0]["subject"] == "y" * 80


# ---------------------------------------------------------------------------
# Empty / malformed proxy payloads
# ---------------------------------------------------------------------------


class TestEmptyResponses:
    @pytest.mark.parametrize("empty", [None, {}])
    def test_falsy_proxy_responses_yield_empty_sections(
        self, tools: Any, api: FakeRedditApi, empty: Any
    ) -> None:
        api.me = empty
        api.subs = empty
        api.messages = empty

        result = _call(tools)

        assert result == {
            "user": dict(DEFAULT_USER),
            "subscribed_subreddits": [],
            "unread_messages": [],
            "unread_message_count": 0,
        }
        # `or {}` handles falsy payloads without treating them as failures.
        api.log.set.assert_not_called()
        api.log.error.assert_not_called()

    def test_data_present_but_without_children(self, tools: Any, api: FakeRedditApi) -> None:
        api.subs = {"data": {}}
        api.messages = {"data": {}}

        result = _call(tools)

        assert result["subscribed_subreddits"] == []
        assert result["unread_messages"] == []
        api.log.set.assert_not_called()
        api.log.error.assert_not_called()

    def test_malformed_child_degrades_the_whole_section(self, tools: Any, api: FakeRedditApi) -> None:
        # The comprehension is inside the try, so a child missing `data`
        # (KeyError) aborts the whole subreddits section and logs a failure
        # rather than crashing the tool or partially filling the list.
        api.subs = {"data": {"children": [{"data": {"display_name": "r/ok"}}, {"nested": True}]}}
        api.messages = {"data": {"children": [{"data": {"id": "m1"}}]}}

        result = _call(tools)

        assert result["subscribed_subreddits"] == []
        assert result["unread_messages"] == [{"id": "m1", "subject": "", "author": None, "created_utc": None}]
        api.log.set.assert_called_once_with(user_id=USER_ID, endpoint=SUBS_ENDPOINT, toolkit=REDDIT_TOOLKIT)
        assert api.log.error.call_count == 1
        assert api.log.error.call_args.args == (SUBS_ERROR_LOG,)
        assert isinstance(api.log.error.call_args.kwargs["exc"], KeyError)


# ---------------------------------------------------------------------------
# Proxy failures -> graceful degradation + wide-event logging
# ---------------------------------------------------------------------------


class TestFetchFailures:
    def test_me_failure_is_logged_and_degrades_to_default_user(
        self, tools: Any, api: FakeRedditApi
    ) -> None:
        err = AppError(message="Reddit API error (401)", why="token expired", status_code=401)
        api.me_error = err
        api.subs = {"data": {"children": [{"data": {"display_name": "r/x", "title": "X", "subscribers": 5}}]}}
        api.messages = {"data": {"children": [{"data": {"id": "m1", "subject": "S", "author": "a", "created_utc": 1}}]}}

        result = _call(tools)

        assert result["user"] == dict(DEFAULT_USER)
        assert result["subscribed_subreddits"] == [{"name": "r/x", "title": "X", "subscribers": 5}]
        assert result["unread_messages"] == [{"id": "m1", "subject": "S", "author": "a", "created_utc": 1}]
        api.log.set.assert_called_once_with(user_id=USER_ID, endpoint=ME_ENDPOINT, toolkit=REDDIT_TOOLKIT)
        api.log.error.assert_called_once_with(ME_ERROR_LOG, exc=err)

    def test_non_app_errors_are_swallowed_identically(self, tools: Any, api: FakeRedditApi) -> None:
        err = RuntimeError("connection reset")
        api.me_error = err
        api.subs = {}
        api.messages = {}

        result = _call(tools)

        assert result["user"] == dict(DEFAULT_USER)
        api.log.set.assert_called_once_with(user_id=USER_ID, endpoint=ME_ENDPOINT, toolkit=REDDIT_TOOLKIT)
        api.log.error.assert_called_once_with(ME_ERROR_LOG, exc=err)

    def test_subreddits_failure_is_logged_and_degrades_to_empty(
        self, tools: Any, api: FakeRedditApi
    ) -> None:
        err = RuntimeError("subs down")
        api.subs_error = err
        api.me = {"name": "gaia_user"}
        api.messages = {"data": {"children": [{"data": {"id": "m1"}}]}}

        result = _call(tools)

        assert result["user"]["name"] == "gaia_user"
        assert result["subscribed_subreddits"] == []
        assert result["unread_messages"] == [{"id": "m1", "subject": "", "author": None, "created_utc": None}]
        api.log.set.assert_called_once_with(user_id=USER_ID, endpoint=SUBS_ENDPOINT, toolkit=REDDIT_TOOLKIT)
        api.log.error.assert_called_once_with(SUBS_ERROR_LOG, exc=err)

    def test_messages_failure_is_logged_and_degrades_to_empty(
        self, tools: Any, api: FakeRedditApi
    ) -> None:
        err = AppError(message="msg down", status_code=500)
        api.messages_error = err
        api.me = {"name": "gaia_user"}
        api.subs = {"data": {"children": []}}

        result = _call(tools)

        assert result["user"]["name"] == "gaia_user"
        assert result["unread_messages"] == []
        assert result["unread_message_count"] == 0
        api.log.set.assert_called_once_with(user_id=USER_ID, endpoint=MESSAGES_ENDPOINT, toolkit=REDDIT_TOOLKIT)
        api.log.error.assert_called_once_with(MESSAGES_ERROR_LOG, exc=err)
