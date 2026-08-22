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

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_LIVE_TIER = Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    """Mark this tier so the default run skips it — these tests bill real Composio calls.

    Scoped to this directory by path, not by the substring "composio": that
    matched every hermetic test whose path merely mentions Composio
    (`tests/unit/services/composio/`, `tests/unit/api/test_webhook_composio_endpoint.py`,
    `tests/integration/real/test_webhook_composio.py` — 545 tests in 18 files) and
    silently dropped all of them from every CI run, since the default marker
    expression is `not composio`. Targeting one of those files directly still
    collected it, because this conftest never loaded, so the gap was invisible
    locally.
    """
    for item in items:
        if _LIVE_TIER in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.composio)


# ---------------------------------------------------------------------------
# Fake credential fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gmail_credentials() -> dict[str, Any]:
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
    registered_tools: dict[str, Any] = {}

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


# Live-credential tier: declare the real keys these tests may use so the root
# hermetic fence (tests/conftest.py) does not blank them. Set at import time —
# before the session fence runs. Only keys needed by genuine live tests belong
# here; mocked tests do not require them.
import os

os.environ.setdefault(
    "HERMETIC_ALLOW_KEYS",
    "COMPOSIO_KEY,COMPOSIO_WEBHOOK_SECRET",
)
