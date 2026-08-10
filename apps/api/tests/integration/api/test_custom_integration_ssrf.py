"""End-to-end wiring: the custom-integration create route rejects SSRF URLs.

Confirms the ``server_url`` shape validator actually fires through the HTTP
request cycle (routing + body validation), not just when the model is built
directly — a private/metadata/non-http URL must be a 422 before any handler or
outbound connection runs.
"""

from httpx import AsyncClient
import pytest

_URL = "/api/v1/integrations/custom"

BLOCKED_URLS = [
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://127.0.0.1:9000/mcp",  # loopback
    "https://10.1.2.3/mcp",  # private
    "ftp://example.com/mcp",  # non-http scheme
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
async def test_create_custom_integration_rejects_ssrf_url(
    test_client: AsyncClient, url: str
) -> None:
    response = await test_client.post(_URL, json={"name": "evil", "server_url": url})

    assert response.status_code == 422
    body = response.json()
    # The rejection must be attributed to server_url, not some unrelated field.
    assert any("server_url" in str(err.get("loc", "")) for err in body["detail"])


async def test_create_custom_integration_requires_auth(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        _URL, json={"name": "x", "server_url": "https://mcp.example.com/sse"}
    )
    assert response.status_code == 401
