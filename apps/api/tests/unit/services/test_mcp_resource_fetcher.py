"""Unit tests for mcp_resource_fetcher (MCP Apps UI resource fetch)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource

_MOD = "app.services.mcp.mcp_resource_fetcher"

SERVER_URL = "https://mcp.example.com/mcp"
RESOURCE_URI = "ui://get-time/app.html"
USER_ID = "507f1f77bcf86cd799439011"


def _details() -> dict:
    return {"html": "<html>clock</html>", "csp": {"default-src": "*"}, "permissions": []}


@pytest.fixture
def mock_client():
    mcp_client = AsyncMock()
    mcp_client.read_ui_resource_details.return_value = _details()
    with patch(f"{_MOD}.get_mcp_client", AsyncMock(return_value=mcp_client)):
        yield mcp_client


class TestFetchMcpUiResource:
    async def test_returns_resource_details(self, mock_client):
        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result == _details()
        mock_client.read_ui_resource_details.assert_awaited_once_with(
            server_url=SERVER_URL, resource_uri=RESOURCE_URI
        )

    async def test_returns_none_on_fetch_failure(self, mock_client):
        mock_client.read_ui_resource_details.side_effect = RuntimeError("server exploded")

        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None

    async def test_returns_none_when_client_unavailable(self):
        with patch(f"{_MOD}.get_mcp_client", AsyncMock(side_effect=ConnectionError("no creds"))):
            result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None

    async def test_returns_none_on_missing_resource(self, mock_client):
        mock_client.read_ui_resource_details.return_value = None

        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None
