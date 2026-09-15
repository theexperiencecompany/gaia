"""Behavior tests for the Microsoft Teams custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool
routes through proxy_request_sync; these tests pin the exact Graph requests
it sends and what it does with the proxy's responses — the /me projection,
the joined-teams and chats projections, the unread count, and the per-call
degradation paths.
"""

from typing import Any
from unittest.mock import patch

import pytest

from app.agents.tools.integrations.microsoft_teams_tool import (
    register_microsoft_teams_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest

MODULE = "app.agents.tools.integrations.microsoft_teams_tool"

AUTH_CREDS = {"user_id": "user_test_123"}

_ME = {
    "id": "u-1",
    "displayName": "Me User",
    "mail": "me@example.com",
    "userPrincipalName": "me@corp.example.com",
}

_TEAMS = {
    "value": [
        {"id": "t-1", "displayName": "Engineering", "description": "Builders"},
        {"id": "t-2", "displayName": "No description"},
    ]
}

_CHATS = {
    "value": [
        {
            "id": "chat-1",
            "topic": "Launch",
            "chatType": "group",
            "lastMessagePreview": {"isRead": False, "body": {"content": "x" * 150}},
        },
        {
            "id": "chat-2",
            "topic": None,
            "chatType": "oneOnOne",
            "lastMessagePreview": {"isRead": True, "body": {"content": "hi"}},
        },
        {"id": "chat-3", "chatType": "meeting"},
    ]
}


def _capture_tool() -> Any:
    tools: dict[str, Any] = {}
    composio = type("Composio", (), {})()
    composio.tools = type("Tools", (), {})()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_microsoft_teams_custom_tools(composio)
    assert registered == ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]
    return tools["CUSTOM_GATHER_CONTEXT"]


def test_sends_me_teams_and_chats_requests_through_the_proxy() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _TEAMS, _CHATS]) as proxy:
        tool(GatherContextInput(), None, AUTH_CREDS)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user_test_123",
            toolkit="MICROSOFT_TEAMS",
            endpoint="https://graph.microsoft.com/v1.0/me",
            method="GET",
            query={"$select": "id,displayName,mail,userPrincipalName"},
        ),
        ProxyRequest(
            user_id="user_test_123",
            toolkit="MICROSOFT_TEAMS",
            endpoint="https://graph.microsoft.com/v1.0/me/joinedTeams",
            method="GET",
            query={"$select": "id,displayName,description"},
        ),
        ProxyRequest(
            user_id="user_test_123",
            toolkit="MICROSOFT_TEAMS",
            endpoint="https://graph.microsoft.com/v1.0/me/chats",
            method="GET",
            query={"$expand": "lastMessagePreview", "$top": 10},
        ),
    ]


def test_projects_user_teams_and_chats_with_counts() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_ME, _TEAMS, _CHATS]):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {
        "user": {"id": "u-1", "display_name": "Me User", "email": "me@example.com"},
        "teams": [
            {"id": "t-1", "name": "Engineering", "description": "Builders"},
            {"id": "t-2", "name": "No description", "description": None},
        ],
        "recent_chats": [
            {
                "id": "chat-1",
                "topic": "Launch",
                "chat_type": "group",
                "last_message_preview": "x" * 100,
                "is_read": False,
            },
            {
                "id": "chat-2",
                "topic": None,
                "chat_type": "oneOnOne",
                "last_message_preview": "hi",
                "is_read": True,
            },
            {
                "id": "chat-3",
                "topic": None,
                "chat_type": "meeting",
                "last_message_preview": None,
                "is_read": True,
            },
        ],
        "team_count": 2,
        "chat_count": 3,
        "unread_chat_count": 1,
    }


def test_email_falls_back_to_user_principal_name() -> None:
    tool = _capture_tool()
    me = {"id": "u-1", "displayName": "Me User", "mail": None, "userPrincipalName": "upn@x.io"}
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[me, {}, {}]):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"] == {"id": "u-1", "display_name": "Me User", "email": "upn@x.io"}


def test_missing_user_id_raises() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
        with pytest.raises(ValueError, match="Missing user_id"):
            tool(GatherContextInput(), None, {})

    assert proxy.call_args_list == []


def test_degraded_proxy_returns_empty_snapshot() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value=None):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {
        "user": {"id": None, "display_name": None, "email": None},
        "teams": [],
        "recent_chats": [],
        "team_count": 0,
        "chat_count": 0,
        "unread_chat_count": 0,
    }


def test_me_failure_leaves_user_empty_and_keeps_teams_and_chats() -> None:
    tool = _capture_tool()
    with patch(
        f"{MODULE}.proxy_request_sync", side_effect=[RuntimeError("scope missing"), _TEAMS, _CHATS]
    ):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"] == {}
    assert result["team_count"] == 2
    assert result["chat_count"] == 3


def test_teams_failure_keeps_user_and_chats() -> None:
    tool = _capture_tool()
    with patch(
        f"{MODULE}.proxy_request_sync", side_effect=[_ME, RuntimeError("scope missing"), _CHATS]
    ):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"]["id"] == "u-1"
    assert result["teams"] == []
    assert result["team_count"] == 0
    assert result["chat_count"] == 3


def test_chats_failure_keeps_user_and_teams() -> None:
    tool = _capture_tool()
    with patch(
        f"{MODULE}.proxy_request_sync", side_effect=[_ME, _TEAMS, RuntimeError("scope missing")]
    ):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"]["id"] == "u-1"
    assert result["team_count"] == 2
    assert result["recent_chats"] == []
    assert result["chat_count"] == 0
    assert result["unread_chat_count"] == 0
