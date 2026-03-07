"""Composio test fixtures.

Provides mocking infrastructure for Gmail custom tool tests.
No real API credentials or network calls are made.
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "composio" in str(item.fspath):
            item.add_marker(pytest.mark.composio)


# ---------------------------------------------------------------------------
# Fake credential fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gmail_credentials() -> Dict[str, Any]:
    """Fake OAuth credentials as supplied by Composio auth_credentials."""
    return {
        "access_token": "test_access_token_abc123",
        "refresh_token": "test_refresh_token_xyz789",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "https://mail.google.com/",
    }


@pytest.fixture
def mock_gmail_credentials_no_token() -> Dict[str, Any]:
    """OAuth credentials dict that is missing the access_token."""
    return {
        "refresh_token": "test_refresh_token_xyz789",
        "token_type": "Bearer",
    }


# ---------------------------------------------------------------------------
# Mock HTTP client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client():
    """
    Returns a MagicMock that replaces the module-level _http_client in
    gmail_tools.  Tests patch the client directly and configure .post/.get
    return values per scenario.
    """
    return MagicMock()


# ---------------------------------------------------------------------------
# Composio mock client (for tool registration)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_composio_client():
    """
    Minimal mock of the Composio SDK client.

    The @composio.tools.custom_tool(toolkit=...) decorator is called during
    register_gmail_custom_tools().  We capture each registered function so
    tests can invoke it directly.
    """
    registered_tools: Dict[str, Any] = {}

    def custom_tool_decorator(toolkit: str):
        """Simulate @composio.tools.custom_tool(toolkit=...)."""

        def decorator(fn):
            # Store tool indexed by its function name so tests can look it up
            registered_tools[fn.__name__] = fn
            return fn

        return decorator

    composio = MagicMock()
    composio.tools.custom_tool.side_effect = custom_tool_decorator
    composio._registered_tools = registered_tools
    return composio
