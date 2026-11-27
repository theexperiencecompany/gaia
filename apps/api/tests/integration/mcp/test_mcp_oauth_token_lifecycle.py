"""An MCP OAuth grant across its life: authorize, code exchange, refresh, and a live session past expiry.

The fake authorization server binds each code and refresh token to the client_id it
was issued to and its MCP endpoint accepts only live access tokens, as real ones do,
so a phase that resolves another client, or a session that keeps a dead token, fails
the way production did for Client ID Metadata Document integrations.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
import secrets
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from mcp.shared.auth import OAuthMetadata
from mcp_use.client.connectors.http import HttpConnector
import pytest

from app.config.settings import settings
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_client import MCPClient
from app.services.mcp.mcp_oauth import build_oauth_auth_url, handle_oauth_callback
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.token_management import try_refresh_token

INTEGRATION_ID = "cimd-integration"
API_BASE = "https://api.gaia.test"
METADATA_DOCUMENT_URL = f"{API_BASE}/api/v1/oauth/client-metadata.json"
REDIRECT_URI = f"{API_BASE}/api/v1/mcp/oauth/callback"
AUTH_SERVER = "https://auth.mcp.test"
MCP_URL = "https://mcp.test/mcp"

# A refresh holds the grant lock; every test gets its own Redis for it.
pytestmark = pytest.mark.usefixtures("fake_redis")


@dataclass
class _FakeAuthorizationServer:
    """Token endpoint that honours a grant only for its client_id, and an MCP endpoint for live tokens."""

    grant_owner: dict[str, str] = field(default_factory=dict)
    token_requests: list[dict[str, str]] = field(default_factory=list)
    live_access_tokens: set[str] = field(default_factory=set)

    def issue_code(self, client_id: str) -> str:
        code = secrets.token_urlsafe(8)
        self.grant_owner[code] = client_id
        return code

    def expire_access_tokens(self) -> None:
        self.live_access_tokens.clear()

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == MCP_URL:
            bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
            return httpx.Response(200 if bearer in self.live_access_tokens else 401)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        grant = form.get("code") or form.get("refresh_token", "")
        if self.grant_owner.pop(grant, None) != form.get("client_id"):
            return httpx.Response(401, json={"error": "invalid_client"})
        refresh_token, access_token = secrets.token_urlsafe(8), secrets.token_urlsafe(8)
        self.grant_owner[refresh_token] = form["client_id"]
        self.live_access_tokens.add(access_token)
        return httpx.Response(
            200,
            json={
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 60,
                "refresh_token": refresh_token,
            },
        )


def _cimd_discovery() -> OAuthDiscovery:
    return OAuthDiscovery(
        as_metadata=OAuthMetadata.model_validate(
            {
                "issuer": AUTH_SERVER,
                "authorization_endpoint": f"{AUTH_SERVER}/authorize",
                "token_endpoint": f"{AUTH_SERVER}/token",
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
            }
        ),
        resource="https://mcp.test/mcp",
        discovery_method="rfc9728_prm",
    )


class _InMemoryTokenStore(MCPTokenStore):
    """MCPTokenStore with in-memory persistence: no DCR client, one OAuth state."""

    def __init__(self) -> None:
        super().__init__("user-1")
        self._code_verifier = ""
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def get_dcr_client(self, integration_id: str) -> None:
        return None

    async def create_oauth_state(self, integration_id: str, code_verifier: str) -> str:
        self._code_verifier = code_verifier
        return "state-token"

    async def verify_oauth_state(self, integration_id: str, state: str) -> tuple[bool, str | None]:
        return True, self._code_verifier

    async def get_and_delete_oauth_nonce(self, integration_id: str) -> str | None:
        return None

    async def store_oauth_tokens(
        self,
        integration_id: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token

    async def get_credential(self, integration_id: str) -> None:
        return None

    async def get_bearer_token(self, integration_id: str) -> str | None:
        return None

    async def get_oauth_token(self, integration_id: str) -> str | None:
        return self._access_token

    async def get_refresh_token(self, integration_id: str) -> str | None:
        return self._refresh_token

    async def clear_oauth_grant(self, integration_id: str) -> None:
        self._access_token = None
        self._refresh_token = None


@pytest.fixture
def auth_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeAuthorizationServer]:
    server = _FakeAuthorizationServer()
    monkeypatch.setattr(settings, "HOST", API_BASE)

    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(server.handle))

    resolved = AsyncMock()
    resolved.mcp_config = MCPConfig(server_url=MCP_URL, requires_auth=True)
    with (
        patch("app.services.mcp.mcp_oauth.mcp_http_client", http_client),
        patch("app.services.mcp.token_management.mcp_http_client", http_client),
        patch(
            "app.services.mcp.mcp_oauth.IntegrationResolver.resolve",
            AsyncMock(return_value=resolved),
        ),
        patch(
            "app.services.mcp.mcp_oauth.discover_oauth_config",
            AsyncMock(return_value=_cimd_discovery()),
        ),
        patch(
            "app.services.mcp.mcp_client.discover_oauth_config",
            AsyncMock(return_value=_cimd_discovery()),
        ),
        patch("app.services.mcp.mcp_oauth.update_user_integration_status", AsyncMock()),
    ):
        yield server


async def _connect(store: MCPTokenStore, server: _FakeAuthorizationServer) -> None:
    """Run the authorize redirect and the callback's code exchange, as a browser would."""
    auth_url = await build_oauth_auth_url(store, INTEGRATION_ID, REDIRECT_URI)
    client_id = parse_qs(urlparse(auth_url).query)["client_id"][0]
    await handle_oauth_callback(
        store,
        INTEGRATION_ID,
        code=server.issue_code(client_id),
        state="state-token",
        redirect_uri=REDIRECT_URI,
        connect_after_oauth=AsyncMock(),
    )


@pytest.mark.integration
@pytest.mark.regression
async def test_a_metadata_document_client_refreshes_as_the_client_it_connected_as(
    auth_server: _FakeAuthorizationServer,
) -> None:
    store = _InMemoryTokenStore()
    await _connect(store, auth_server)

    refreshed = await try_refresh_token(
        store, INTEGRATION_ID, MCPConfig(server_url=MCP_URL), _cimd_discovery()
    )

    assert refreshed is True
    assert [r["grant_type"] for r in auth_server.token_requests] == [
        "authorization_code",
        "refresh_token",
    ]
    assert {r["client_id"] for r in auth_server.token_requests} == {METADATA_DOCUMENT_URL}


@pytest.mark.integration
async def test_a_refresh_no_client_can_present_keeps_the_grant(
    auth_server: _FakeAuthorizationServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _InMemoryTokenStore()
    await _connect(store, auth_server)
    monkeypatch.setattr(settings, "HOST", "http://localhost:8000")

    refreshed = await try_refresh_token(
        store, INTEGRATION_ID, MCPConfig(server_url=MCP_URL), _cimd_discovery()
    )

    assert refreshed is False
    assert await store.get_refresh_token(INTEGRATION_ID) is not None
    assert [r["grant_type"] for r in auth_server.token_requests] == ["authorization_code"]


@pytest.mark.integration
@pytest.mark.regression
async def test_a_live_session_refreshes_a_token_the_server_expired_and_retries(
    auth_server: _FakeAuthorizationServer,
) -> None:
    store = _InMemoryTokenStore()
    await _connect(store, auth_server)
    client = MCPClient("user-1")
    client.token_store = store
    config = await client._build_config(
        INTEGRATION_ID, MCPConfig(server_url=MCP_URL, requires_auth=True)
    )
    server = config["mcpServers"][INTEGRATION_ID]
    # The connector mcp_use builds from this config; its session sends with these headers and auth.
    connector = HttpConnector(
        base_url=MCP_URL, headers=server.get("headers"), auth=server.get("auth")
    )
    auth_server.expire_access_tokens()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(auth_server.handle),
        headers=connector.headers,
        auth=connector._auth,
    ) as session_http:
        response = await session_http.post(MCP_URL)

    assert response.status_code == 200
    assert [r["grant_type"] for r in auth_server.token_requests] == [
        "authorization_code",
        "refresh_token",
    ]
