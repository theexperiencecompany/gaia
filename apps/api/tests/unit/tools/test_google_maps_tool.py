"""Behavior tests for the Google Maps custom tool (CUSTOM_GATHER_CONTEXT).

The proxy smoke test (test_integration_tools_proxy.py) proves the tool
routes through proxy_request_sync; these tests pin the exact geocode probe
it sends and how the probe's status maps to the connectivity snapshot.
"""

from typing import Any
from unittest.mock import patch

import pytest

from app.agents.tools.integrations.google_maps_tool import register_google_maps_custom_tools
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import ProxyRequest
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.google_maps_tool"

AUTH_CREDS = {"user_id": "user_test_123"}

_SERVICES = ["geocoding", "places", "directions", "distance_matrix", "elevation", "timezone"]


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
    registered = register_google_maps_custom_tools(composio)
    assert registered == ["GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT"]
    return tools["CUSTOM_GATHER_CONTEXT"]


def test_sends_geocode_probe_through_the_proxy() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={"status": "OK"}) as proxy:
        tool(GatherContextInput(), None, AUTH_CREDS)

    assert [c.args[0] for c in proxy.call_args_list] == [
        ProxyRequest(
            user_id="user_test_123",
            toolkit="GOOGLE_MAPS",
            endpoint="https://maps.googleapis.com/maps/api/geocode/json",
            method="GET",
            query={"address": "New York, NY", "result_type": "locality"},
        )
    ]


def test_ok_status_reports_connected() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={"status": "OK", "results": []}):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {"api_connected": True, "status": "OK", "available_services": _SERVICES}


def test_non_ok_status_is_passed_through_as_not_connected() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={"status": "REQUEST_DENIED"}):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {
        "api_connected": False,
        "status": "REQUEST_DENIED",
        "available_services": _SERVICES,
    }


def test_empty_proxy_response_reports_unknown() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value=None):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {"api_connected": False, "status": "UNKNOWN", "available_services": _SERVICES}


def test_proxy_failure_reports_error() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", side_effect=RuntimeError("not connected")):
        result = tool(GatherContextInput(), None, AUTH_CREDS)

    assert result == {"api_connected": False, "status": "ERROR", "available_services": _SERVICES}


def test_missing_user_id_raises() -> None:
    tool = _capture_tool()
    with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
        with pytest.raises(AppError, match="Missing user_id"):
            tool(GatherContextInput(), None, {})

    assert proxy.call_args_list == []
