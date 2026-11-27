"""resolve_oauth_client: the one answer to which OAuth client an MCP integration uses."""

from unittest.mock import AsyncMock

from mcp.shared.auth import OAuthMetadata
import pytest

from app.config.settings import settings
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.oauth_client import OAuthClient, resolve_oauth_client

INTEGRATION_ID = "custom_oauth"
PUBLIC_API = "https://api.gaia.test"


def _discovery(*, metadata_document: bool) -> OAuthDiscovery:
    return OAuthDiscovery(
        as_metadata=OAuthMetadata.model_validate(
            {
                "issuer": "https://auth.mcp.test",
                "authorization_endpoint": "https://auth.mcp.test/authorize",
                "token_endpoint": "https://auth.mcp.test/token",
                "client_id_metadata_document_supported": metadata_document,
            }
        ),
        resource="https://mcp.test/mcp",
        discovery_method="direct",
    )


def _store(registration: dict[str, str] | None = None) -> AsyncMock:
    store = AsyncMock(spec=MCPTokenStore)
    store.get_dcr_client.return_value = registration
    return store


def _config(**fields: object) -> MCPConfig:
    return MCPConfig.model_validate({"server_url": "https://mcp.test/mcp", **fields})


@pytest.fixture(autouse=True)
def _public_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HOST", PUBLIC_API)


@pytest.mark.unit
class TestResolveOAuthClient:
    async def test_configured_credentials_win_without_reading_the_registration(self) -> None:
        store = _store({"client_id": "dcr-id"})

        client = await resolve_oauth_client(
            store,
            INTEGRATION_ID,
            _config(client_id="cfg-id", client_secret="cfg-secret"),
            _discovery(metadata_document=True),
        )

        assert client == OAuthClient("cfg-id", "cfg-secret")
        store.get_dcr_client.assert_not_awaited()

    async def test_a_stored_registration_beats_the_metadata_document(self) -> None:
        store = _store({"client_id": "dcr-id", "client_secret": "dcr-secret"})

        client = await resolve_oauth_client(
            store, INTEGRATION_ID, _config(), _discovery(metadata_document=True)
        )

        assert client == OAuthClient("dcr-id", "dcr-secret")
        store.get_dcr_client.assert_awaited_once_with(INTEGRATION_ID)

    async def test_the_metadata_document_url_is_a_public_client(self) -> None:
        client = await resolve_oauth_client(
            _store(), INTEGRATION_ID, _config(), _discovery(metadata_document=True)
        )

        assert client == OAuthClient(f"{PUBLIC_API}/api/v1/oauth/client-metadata.json", None)

    async def test_no_client_when_the_server_does_not_accept_metadata_documents(self) -> None:
        client = await resolve_oauth_client(
            _store(), INTEGRATION_ID, _config(), _discovery(metadata_document=False)
        )

        assert client is None

    async def test_a_localhost_api_never_offers_its_metadata_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HOST", "http://localhost:8000")

        client = await resolve_oauth_client(
            _store(), INTEGRATION_ID, _config(), _discovery(metadata_document=True)
        )

        assert client is None
