"""End-to-end wiring: the custom-integration create route rejects SSRF URLs and public plain-http sign-ins."""

from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
import pytest

from app.config.settings import settings
from app.db.repositories.integrations import integration_repository
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig

_URL = "/api/v1/integrations/custom"

BLOCKED_URLS = [
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://127.0.0.1:9000/mcp",  # loopback
    "https://10.1.2.3/mcp",  # private
    "ftp://example.com/mcp",  # non-http scheme
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
async def test_create_custom_integration_rejects_ssrf_url_on_gaia_cloud(
    test_client: AsyncClient, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    response = await test_client.post(_URL, json={"name": "evil", "server_url": url})

    assert response.status_code == 422
    body = response.json()
    # The rejection must be attributed to server_url, not some unrelated field.
    assert any("server_url" in str(err.get("loc", "")) for err in body["errors"])


async def test_create_custom_integration_requires_auth(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        _URL, json={"name": "x", "server_url": "https://mcp.example.com/sse"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "auth",
    [{"requires_auth": True, "auth_type": "oauth"}, {"bearer_token": "user-api-key"}],
    ids=["oauth", "bearer"],
)
async def test_adding_a_signed_in_server_on_public_plain_http_is_refused_with_the_https_message(
    test_client: AsyncClient, auth: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The per-user MCP client pool is process infrastructure; the route's own logic runs for real.
    monkeypatch.setattr(
        "app.api.v1.endpoints.integrations.custom.get_mcp_client",
        AsyncMock(return_value=MagicMock()),
    )
    response = await test_client.post(
        _URL, json={"name": "Mine", "server_url": "http://93.184.216.34/mcp", **auth}
    )

    assert response.status_code == 400
    assert response.json()["message"] == (
        "This server needs a sign-in, so its URL has to start with https://. "
        "Plain http works only for a server on this machine or your local network."
    )


async def test_editing_a_signed_in_server_to_public_plain_http_is_refused_with_the_https_message(
    test_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = Integration(
        integration_id="custom-1",
        name="Mine",
        description="Mine",
        category="custom",
        managed_by="mcp",
        created_by="user-1",
        mcp_config=MCPConfig(server_url="https://mcp.example.com/mcp", requires_auth=True),
    )
    # The stored document is the repository's; the route and service logic run for real.
    monkeypatch.setattr(
        integration_repository, "get_custom_for_user", AsyncMock(return_value=stored)
    )
    update = AsyncMock()
    monkeypatch.setattr(integration_repository, "update", update)

    response = await test_client.patch(
        f"{_URL}/custom-1", json={"server_url": "http://93.184.216.34/mcp"}
    )

    assert response.status_code == 400
    assert response.json()["message"] == (
        "This server needs a sign-in, so its URL has to start with https://. "
        "Plain http works only for a server on this machine or your local network."
    )
    update.assert_not_awaited()
