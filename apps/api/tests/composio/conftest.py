"""Composio test fixtures.

After the GAIA-641 proxy migration, the per-toolkit unit tests previously
in this directory (test_gmail.py, test_calendar.py, test_google_docs.py,
test_linkedin.py, test_notion.py, test_twitter.py) were deleted: they
mocked `httpx.Client` against the legacy direct-API contract that no
longer exists. Equivalent coverage now lives in `tests/unit/` and patches
`proxy_request_sync` at the call-site module instead.

Only `test_linear.py` remains because it patches at the
`graphql_request` boundary (which is still the public surface of
`linear_utils`) rather than the now-removed httpx layer.

New live-credential tests added here should patch nothing — they should
exercise the real `proxy_request_sync` path with a real Composio API key
and a real connected account.
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
    """Auth credentials shape Composio passes into custom tools post-migration.

    Composio no longer returns OAuth `access_token` in connected-account
    credentials. The patched `CustomTool.__call__` injects only `user_id`,
    and tools route provider requests through `proxy_request_sync`.
    """
    return {"user_id": "test_user_123"}


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
