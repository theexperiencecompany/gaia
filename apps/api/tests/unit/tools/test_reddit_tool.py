"""Behavior tests for the Reddit custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool routes
through proxy_request_sync and test_platform_integration_tools.py pins the
response shaping; these pin the exact OAuth API requests the tool sends —
endpoint, method, `limit` query and the User-Agent header Reddit requires —
and the full result shape, including each fetch degrading independently.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.reddit_tool import (
    REDDIT_API_BASE,
    register_reddit_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.reddit_tool"
AUTH: dict[str, Any] = {"user_id": "user-42"}
EXECUTE_REQUEST = MagicMock()
HEADERS = {"User-Agent": "GAIA/1.0"}

_ME = {
    "name": "ada",
    "id": "r-1",
    "link_karma": 10,
    "comment_karma": 20,
    "total_karma": 30,
    "icon_img": "https://reddit/ada.png",
    "is_gold": True,
}

_SUBS = {
    "data": {
        "children": [
            {"data": {"display_name": "python", "title": "t" * 100, "subscribers": 5}},
            {"data": {"display_name": "rust"}},
        ]
    }
}

_UNREAD = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "msg-1",
                    "subject": "s" * 100,
                    "author": "bob",
                    "created_utc": 1700000000.0,
                }
            },
            {"data": {"id": "msg-2"}},
        ]
    }
}


@pytest.fixture
def tool() -> Any:
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    assert register_reddit_custom_tools(composio) == ["REDDIT_CUSTOM_GATHER_CONTEXT"]
    return captured["CUSTOM_GATHER_CONTEXT"]


def test_sends_profile_subreddits_and_unread_requests(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _SUBS, _UNREAD]) as proxy:
        tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user-42",
            toolkit="REDDIT",
            endpoint=f"{REDDIT_API_BASE}/api/v1/me",
            method="GET",
            headers=HEADERS,
        ),
        ProxyRequest(
            user_id="user-42",
            toolkit="REDDIT",
            endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
            method="GET",
            query={"limit": 5},
            headers=HEADERS,
        ),
        ProxyRequest(
            user_id="user-42",
            toolkit="REDDIT",
            endpoint=f"{REDDIT_API_BASE}/message/unread",
            method="GET",
            query={"limit": 5},
            headers=HEADERS,
        ),
    ]


def test_returns_profile_subreddits_and_truncated_unread(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _SUBS, _UNREAD]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out == {
        "user": {
            "name": "ada",
            "id": "r-1",
            "link_karma": 10,
            "comment_karma": 20,
            "total_karma": 30,
            "icon_img": "https://reddit/ada.png",
            "is_gold": True,
        },
        "subscribed_subreddits": [
            {"name": "python", "title": "t" * 80, "subscribers": 5},
            {"name": "rust", "title": "", "subscribers": 0},
        ],
        "unread_messages": [
            {"id": "msg-1", "subject": "s" * 80, "author": "bob", "created_utc": 1700000000.0},
            {"id": "msg-2", "subject": "", "author": None, "created_utc": None},
        ],
        "unread_message_count": 2,
    }


def test_degraded_proxy_returns_empty_snapshot(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out == {
        "user": {
            "name": None,
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        },
        "subscribed_subreddits": [],
        "unread_messages": [],
        "unread_message_count": 0,
    }


def test_profile_failure_keeps_subreddits_and_unread(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[RuntimeError("403"), _SUBS, _UNREAD]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out["user"]["name"] is None
    assert [s["name"] for s in out["subscribed_subreddits"]] == ["python", "rust"]
    assert out["unread_message_count"] == 2


def test_subreddits_failure_keeps_profile_and_unread(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, RuntimeError("scope"), _UNREAD]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out["user"]["name"] == "ada"
    assert out["subscribed_subreddits"] == []
    assert out["unread_message_count"] == 2


def test_unread_failure_keeps_profile_and_subreddits(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _SUBS, RuntimeError("scope")]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out["user"]["name"] == "ada"
    assert [s["name"] for s in out["subscribed_subreddits"]] == ["python", "rust"]
    assert out["unread_messages"] == []
    assert out["unread_message_count"] == 0


def test_missing_user_id_raises_before_any_request(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        with pytest.raises(AppError) as exc_info:
            tool(GatherContextInput(), EXECUTE_REQUEST, {})

    assert exc_info.value.status_code == 500
    assert exc_info.value.message == "Missing user_id in auth_credentials"
    proxy.assert_not_called()
