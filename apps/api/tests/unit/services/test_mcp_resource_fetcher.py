"""Unit tests for mcp_resource_fetcher (MCP Apps UI resource fetch)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource

_MOD = "app.services.mcp.mcp_resource_fetcher"

SERVER_URL = "https://mcp.example.com/mcp"
RESOURCE_URI = "ui://get-time/app.html"
USER_ID = "507f1f77bcf86cd799439011"


def _details() -> dict:
    return {"html": "<html>clock</html>", "csp": {"default-src": "*"}, "permissions": []}


@pytest.fixture
def mock_client() -> Iterator[MagicMock]:
    mcp_client = MagicMock()
    with patch(f"{_MOD}.get_mcp_client", AsyncMock(return_value=mcp_client)):
        yield mcp_client


@pytest.fixture
def read_details(mock_client: MagicMock) -> Iterator[AsyncMock]:
    with patch(
        f"{_MOD}.read_ui_resource_details", new_callable=AsyncMock, return_value=_details()
    ) as mock:
        yield mock


class TestFetchMcpUiResource:
    async def test_returns_resource_details(self, mock_client, read_details):
        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result == _details()
        read_details.assert_awaited_once_with(
            mock_client, server_url=SERVER_URL, resource_uri=RESOURCE_URI
        )

    async def test_returns_none_on_fetch_failure(self, read_details):
        read_details.side_effect = RuntimeError("server exploded")

        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None

    async def test_returns_none_when_client_unavailable(self):
        with patch(f"{_MOD}.get_mcp_client", AsyncMock(side_effect=ConnectionError("no creds"))):
            result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None

    async def test_returns_none_on_missing_resource(self, read_details):
        read_details.return_value = None

        result = await fetch_mcp_ui_resource(SERVER_URL, RESOURCE_URI, USER_ID)

        assert result is None
