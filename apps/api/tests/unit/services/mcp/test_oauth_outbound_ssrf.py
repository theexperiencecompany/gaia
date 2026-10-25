"""Every MCP OAuth request to a server-supplied URL passes the endpoint SSRF guard.

The authorization server hands back its own registration, token and metadata
URLs, so each is checked before it is dialed: GAIA Cloud refuses private
addresses, a self-hosted instance reaches its own network.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from mcp.shared.auth import OAuthMetadata
import pytest
import respx

from app.config.settings import settings
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_client import MCPClient
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.token_management import try_refresh_token
from app.utils.mcp_oauth_utils import fetch_auth_server_metadata, fetch_protected_resource_metadata

AUTH_HOST = "auth.mcp.example"
PRIVATE_ADDRESS = "10.0.0.7"
INTEGRATION_ID = "custom_ssrf"


@pytest.fixture
def auth_host_is_private() -> Iterator[None]:
    with patch("app.utils.url_safety._resolve", return_value=[PRIVATE_ADDRESS]):
        yield


def _metadata() -> OAuthMetadata:
    return OAuthMetadata.model_validate(
        {
            "issuer": f"https://{AUTH_HOST}",
            "authorization_endpoint": f"https://{AUTH_HOST}/authorize",
            "token_endpoint": f"https://{AUTH_HOST}/token",
            "registration_endpoint": f"https://{AUTH_HOST}/register",
            "code_challenge_methods_supported": ["S256"],
        }
    )


@pytest.mark.usefixtures("auth_host_is_private")
class TestGaiaCloudRefusesPrivateOAuthEndpoints:
    @pytest.fixture(autouse=True)
    def _gaia_cloud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENV", "production")

    @respx.mock(assert_all_called=False)
    async def test_dynamic_client_registration(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.post(f"https://{AUTH_HOST}/register")
        client = MCPClient(user_id="u1")

        with pytest.raises(ValueError, match="non-public"):
            await client._register_client(INTEGRATION_ID, _metadata(), "https://gaia/callback")

        assert not route.called

    @respx.mock(assert_all_called=False)
    async def test_token_exchange(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.post(f"https://{AUTH_HOST}/token")
        client = MCPClient(user_id="u1")

        with pytest.raises(ValueError, match="non-public"):
            await client._exchange_code_for_tokens(
                INTEGRATION_ID,
                f"https://{AUTH_HOST}/token",
                {
                    "code": "c",
                    "redirect_uri": "https://gaia/callback",
                    "resource": "https://mcp.example/mcp",
                    "client_id": "cid",
                    "client_secret": None,
                    "code_verifier": "v",
                },
            )

        assert not route.called

    @respx.mock(assert_all_called=False)
    async def test_token_refresh(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.post(f"https://{AUTH_HOST}/token")
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = "u1"
        token_store.get_refresh_token = AsyncMock(return_value="refresh")
        oauth_config = OAuthDiscovery(
            as_metadata=_metadata(), resource="https://mcp.example/mcp", discovery_method="direct"
        )
        mcp_config = MCPConfig(
            server_url="https://mcp.example/mcp", requires_auth=True, client_id="cid"
        )

        assert not await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)
        assert not route.called

    @respx.mock(assert_all_called=False)
    async def test_protected_resource_metadata(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get(f"https://{AUTH_HOST}/.well-known/oauth-protected-resource")

        with pytest.raises(ValueError, match="non-public"):
            await fetch_protected_resource_metadata(
                f"https://{AUTH_HOST}/.well-known/oauth-protected-resource"
            )

        assert not route.called

    @respx.mock(assert_all_called=False)
    async def test_authorization_server_metadata(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get(url__startswith=f"https://{AUTH_HOST}/")

        await fetch_auth_server_metadata(f"https://{AUTH_HOST}")

        assert not route.called


@pytest.mark.usefixtures("auth_host_is_private")
@respx.mock(assert_all_called=False)
async def test_a_selfhost_instance_registers_with_an_authorization_server_on_its_network(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    route = respx_mock.post(f"https://{AUTH_HOST}/register").respond(
        201, json={"client_id": "registered", "redirect_uris": ["https://gaia/callback"]}
    )
    client = MCPClient(user_id="u1")
    client.token_store = AsyncMock(spec=MCPTokenStore)

    assert (
        await client._register_client(INTEGRATION_ID, _metadata(), "https://gaia/callback")
        == "registered"
    )
    assert route.called
