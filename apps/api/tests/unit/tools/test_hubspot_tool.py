"""Behavior tests for the HubSpot custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool
routes through proxy_request_sync; these tests pin the exact CRM requests
it sends and what it does with the proxy's responses — the contact / deal
projection, the counts, and the per-call degradation paths.
"""

from typing import Any
from unittest.mock import patch

import pytest

from app.agents.tools.integrations.hubspot_tool import register_hubspot_custom_tools
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest

MODULE = "app.agents.tools.integrations.hubspot_tool"

AUTH_CREDS = {"user_id": "user_test_123"}

_CONTACTS = {
    "results": [
        {
            "id": "c-1",
            "properties": {
                "firstname": "Ada",
                "lastname": "Lovelace",
                "email": "ada@example.com",
                "hs_lead_status": "NEW",
                "createdate": "2026-08-01T00:00:00Z",
            },
        },
        {"id": "c-2", "properties": {"firstname": "Bare"}},
    ]
}

_DEALS = {
    "results": [
        {
            "id": "d-1",
            "properties": {
                "dealname": "Big deal",
                "amount": "1000",
                "dealstage": "appointmentscheduled",
                "closedate": "2026-09-01T00:00:00Z",
                "pipeline": "default",
            },
        },
        {"id": "d-2"},
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
    registered = register_hubspot_custom_tools(composio)
    assert registered == ["HUBSPOT_CUSTOM_GATHER_CONTEXT"]
    return tools["CUSTOM_GATHER_CONTEXT"]


def test_sends_contacts_and_deals_requests_through_the_proxy() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_CONTACTS, _DEALS]) as proxy:
        tool(GatherContextInput(), None, AUTH_CREDS)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user_test_123",
            toolkit="HUBSPOT",
            endpoint="https://api.hubapi.com/crm/v3/objects/contacts",
            method="GET",
            query={
                "limit": 10,
                "properties": "firstname,lastname,email,hs_lead_status",
                "sort": "-createdate",
            },
        ),
        ProxyRequest(
            user_id="user_test_123",
            toolkit="HUBSPOT",
            endpoint="https://api.hubapi.com/crm/v3/objects/deals",
            method="GET",
            query={
                "limit": 10,
                "properties": "dealname,amount,dealstage,closedate",
                "sort": "-createdate",
            },
        ),
    ]


def test_projects_contacts_and_deals_with_counts() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[_CONTACTS, _DEALS]):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {
        "recent_contacts": [
            {
                "id": "c-1",
                "firstname": "Ada",
                "lastname": "Lovelace",
                "email": "ada@example.com",
                "lead_status": "NEW",
            },
            {
                "id": "c-2",
                "firstname": "Bare",
                "lastname": None,
                "email": None,
                "lead_status": None,
            },
        ],
        "recent_deals": [
            {
                "id": "d-1",
                "dealname": "Big deal",
                "amount": "1000",
                "dealstage": "appointmentscheduled",
                "closedate": "2026-09-01T00:00:00Z",
            },
            {
                "id": "d-2",
                "dealname": None,
                "amount": None,
                "dealstage": None,
                "closedate": None,
            },
        ],
        "contact_count": 2,
        "deal_count": 2,
    }


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
        "recent_contacts": [],
        "recent_deals": [],
        "contact_count": 0,
        "deal_count": 0,
    }


def test_contacts_failure_keeps_deals() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=[RuntimeError("scope missing"), _DEALS]):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result["recent_contacts"] == []
    assert result["contact_count"] == 0
    assert [d["id"] for d in result["recent_deals"]] == ["d-1", "d-2"]
    assert result["deal_count"] == 2


def test_deals_failure_keeps_contacts() -> None:
    tool = _capture_tool()
    with patch(
        f"{MODULE}.proxy_request_sync", side_effect=[_CONTACTS, RuntimeError("scope missing")]
    ):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert [c["id"] for c in result["recent_contacts"]] == ["c-1", "c-2"]
    assert result["contact_count"] == 2
    assert result["recent_deals"] == []
    assert result["deal_count"] == 0
