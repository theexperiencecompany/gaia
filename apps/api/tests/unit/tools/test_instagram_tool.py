"""Behavior tests for the Instagram custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool routes
through proxy_request_sync and test_platform_integration_tools.py pins the
response shaping; these pin the exact Graph API requests the tool sends —
endpoint, method and the `fields` / `limit` query — and the full result shape.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.instagram_tool import (
    INSTAGRAM_API_BASE,
    register_instagram_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest

MODULE = "app.agents.tools.integrations.instagram_tool"
AUTH: dict[str, Any] = {"user_id": "user-42"}
EXECUTE_REQUEST = MagicMock()

_ME = {
    "id": "ig-1",
    "name": "Ada",
    "username": "ada",
    "account_type": "BUSINESS",
    "media_count": 3,
    "followers_count": 120,
    "follows_count": 15,
    "biography": "b" * 300,
}

_MEDIA = {
    "data": [
        {
            "id": "m1",
            "caption": "c" * 300,
            "media_type": "IMAGE",
            "timestamp": "2026-01-01T00:00:00+0000",
            "like_count": 4,
            "comments_count": 1,
            "permalink": "https://instagram.com/p/m1",
        },
        {"id": "m2", "caption": None, "media_type": "VIDEO"},
    ]
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
    assert register_instagram_custom_tools(composio) == ["INSTAGRAM_CUSTOM_GATHER_CONTEXT"]
    return captured["CUSTOM_GATHER_CONTEXT"]


def test_sends_profile_then_media_requests(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _MEDIA]) as proxy:
        tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user-42",
            toolkit="INSTAGRAM",
            endpoint=f"{INSTAGRAM_API_BASE}/me",
            method="GET",
            query={
                "fields": (
                    "id,name,username,account_type,media_count,"
                    "followers_count,follows_count,biography"
                )
            },
        ),
        ProxyRequest(
            user_id="user-42",
            toolkit="INSTAGRAM",
            endpoint=f"{INSTAGRAM_API_BASE}/me/media",
            method="GET",
            query={
                "limit": "5",
                "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
            },
        ),
    ]


def test_returns_profile_and_truncated_recent_media(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _MEDIA]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out == {
        "user": {
            "id": "ig-1",
            "name": "Ada",
            "username": "ada",
            "account_type": "BUSINESS",
            "media_count": 3,
            "followers": 120,
            "following": 15,
            "biography": "b" * 200,
        },
        "recent_media": [
            {
                "id": "m1",
                "caption": "c" * 100,
                "media_type": "IMAGE",
                "timestamp": "2026-01-01T00:00:00+0000",
                "likes": 4,
                "comments": 1,
                "permalink": "https://instagram.com/p/m1",
            },
            {
                "id": "m2",
                "caption": "",
                "media_type": "VIDEO",
                "timestamp": None,
                "likes": 0,
                "comments": 0,
                "permalink": None,
            },
        ],
    }


def test_degraded_proxy_returns_empty_profile(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out == {
        "user": {
            "id": None,
            "name": None,
            "username": None,
            "account_type": None,
            "media_count": 0,
            "followers": 0,
            "following": 0,
            "biography": "",
        },
        "recent_media": [],
    }


def test_media_failure_keeps_profile(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, RuntimeError("graph down")]):
        out = tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)

    assert out["user"]["username"] == "ada"
    assert out["recent_media"] == []


def test_profile_failure_propagates(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync", side_effect=RuntimeError("graph down")):
        with pytest.raises(RuntimeError, match="graph down"):
            tool(GatherContextInput(), EXECUTE_REQUEST, AUTH)


def test_missing_user_id_raises_before_any_request(tool) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tool(GatherContextInput(), EXECUTE_REQUEST, {})
    proxy.assert_not_called()
