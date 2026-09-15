"""Behavior tests for the Google Meet custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool
routes through proxy_request_sync; these tests pin what it does with the
proxy's responses — the user profile passthrough, the meeting extraction
(conference entry points -> meet links), the count, and the degradation
paths. This is the module the mutation lane derived for this tool.
"""

import datetime
from unittest.mock import patch

import pytest
import time_machine

from app.agents.tools.integrations.google_meet_tool import register_google_meet_custom_tools
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest

MODULE = "app.agents.tools.integrations.google_meet_tool"

AUTH_CREDS = {"user_id": "user_test_123"}

_USERINFO = {
    "email": "me@example.com",
    "name": "Me User",
    "picture": "https://example.com/pic.png",
}

_CALENDAR = {
    "items": [
        {
            "id": "evt-1",
            "summary": "Daily standup",
            "start": {"dateTime": "2026-08-08T10:00:00Z"},
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/abc-def-ghi"}
                ]
            },
        },
        {
            "id": "evt-2",
            "summary": "No link",
            "start": {"date": "2026-08-09"},
        },
    ]
}


def _capture_tool() -> callable:
    tools = {}
    composio = type("Composio", (), {})()
    composio.tools = type("Tools", (), {})()

    def custom_tool(**_kwargs):
        def decorator(fn):
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_google_meet_custom_tools(composio)
    assert registered == ["GOOGLEMEET_CUSTOM_GATHER_CONTEXT"]
    return tools["CUSTOM_GATHER_CONTEXT"]


def test_returns_profile_and_upcoming_meets_with_meet_links() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_USERINFO, _CALENDAR]):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"] == {
        "email": "me@example.com",
        "name": "Me User",
        "picture": "https://example.com/pic.png",
    }
    assert result["upcoming_meets"] == [
        {
            "id": "evt-1",
            "summary": "Daily standup",
            "start": "2026-08-08T10:00:00Z",
            "meet_link": "https://meet.google.com/abc-def-ghi",
        }
    ]
    assert result["upcoming_meet_count"] == 1


def test_sends_userinfo_and_calendar_requests_through_the_proxy() -> None:
    tool = _capture_tool()
    frozen = datetime.datetime(2026, 8, 8, 9, 30, 15, tzinfo=datetime.UTC)
    with (
        time_machine.travel(frozen, tick=False),
        patch(f"{MODULE}.proxy_request_sync", side_effect=[_USERINFO, _CALENDAR]) as proxy,
    ):
        tool(GatherContextInput(), None, AUTH_CREDS)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user_test_123",
            toolkit="GOOGLEMEET",
            endpoint="https://www.googleapis.com/oauth2/v3/userinfo",
            method="GET",
        ),
        ProxyRequest(
            user_id="user_test_123",
            toolkit="GOOGLEMEET",
            endpoint="https://www.googleapis.com/calendar/v3/calendars/primary/events",
            method="GET",
            query={
                "timeMin": "2026-08-08T09:30:15Z",
                "maxResults": 5,
                "singleEvents": "true",
                "orderBy": "startTime",
                "fields": "items(id,summary,start,end,conferenceData,htmlLink)",
            },
        ),
    ]


def test_missing_user_id_raises() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={}):
        with pytest.raises(ValueError, match="Missing user_id"):
            tool(GatherContextInput(), None, {})


def test_degraded_proxy_returns_empty_profile() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={}):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"] == {"email": None, "name": None, "picture": None}
    assert result["upcoming_meets"] == []
    assert result["upcoming_meet_count"] == 0


def test_calendar_failure_keeps_profile() -> None:
    tool = _capture_tool()
    with patch(
        f"{MODULE}.proxy_request_sync", side_effect=[_USERINFO, RuntimeError("scope missing")]
    ):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["user"]["email"] == "me@example.com"
    assert result["upcoming_meets"] == []
    assert result["upcoming_meet_count"] == 0
