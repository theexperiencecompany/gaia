"""Behavior tests for Notion custom tool registration and error paths.

The proxy smoke test (test_integration_tools_proxy.py) proves routing; these
tests pin the exact registration contract (tool names + toolkit kwarg) and
the FETCH_DATA failure paths.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.notion_tool import register_notion_custom_tools
from app.models.notion_models import FetchDataInput
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.notion_tool"

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}

EXPECTED_TOOL_NAMES = [
    "NOTION_MOVE_PAGE",
    "NOTION_FETCH_PAGE_AS_MARKDOWN",
    "NOTION_INSERT_MARKDOWN",
    "NOTION_FETCH_DATA",
    "NOTION_CUSTOM_GATHER_CONTEXT",
]


def _capture_tools(
    register_fn: Callable[..., list[str]],
) -> tuple[list[str], dict[str, tuple[Callable[..., Any], dict[str, Any]]]]:
    captured: dict[str, tuple[Callable[..., Any], dict[str, Any]]] = {}
    composio = MagicMock()

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = (fn, kwargs)
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_fn(composio)
    return registered, captured


def test_register_returns_exact_tool_names_and_toolkits() -> None:
    registered, captured = _capture_tools(register_notion_custom_tools)

    assert registered == EXPECTED_TOOL_NAMES
    assert sorted(captured) == sorted(EXPECTED_TOOL_NAMES)
    assert all(kwargs == {"toolkit": "NOTION"} for _, kwargs in captured.values())


def test_fetch_data_app_error_raises_runtime_error_with_message() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["FETCH_DATA"]
    error = AppError(message="Notion API error (500)", status_code=500)

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error):
        with pytest.raises(RuntimeError) as excinfo:
            fetch_data(FetchDataInput(fetch_type="pages"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch pages: Notion API error (500)"
    assert excinfo.value.__cause__ is error


def test_fetch_data_unexpected_error_raises_runtime_error_with_str() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["FETCH_DATA"]
    error = ValueError("connection reset")

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error):
        with pytest.raises(RuntimeError) as excinfo:
            fetch_data(FetchDataInput(fetch_type="databases"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch databases: connection reset"
    assert excinfo.value.__cause__ is error
