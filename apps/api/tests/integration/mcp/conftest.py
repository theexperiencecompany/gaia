"""Shared fixtures for MCP integration tests."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_ssrf_guard():
    """Neutralize the DNS-resolving SSRF guard for the whole MCP integration suite.

    ``_do_connect`` and ``probe_mcp_connection`` call ``assert_public_http_url``,
    which performs real DNS resolution. Integration tests use fake hostnames that
    do not resolve, so patch the guard to a no-op where it is used.
    """
    with (
        patch(
            "app.services.mcp.mcp_client.assert_public_http_url",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.mcp.oauth_discovery.assert_public_http_url",
            new_callable=AsyncMock,
        ),
    ):
        yield
