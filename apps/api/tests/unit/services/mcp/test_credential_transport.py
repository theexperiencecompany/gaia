"""An OAuth or bearer token never goes to an MCP server over plain http outside the local network.

Each test drives one place a token is attached or a sign-in is started: the session
config, the OAuth authorization URL, a reconnect and adding a custom server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.integration_models import CreateCustomIntegrationRequest
from app.models.mcp_config import MCPConfig
from app.services.integrations.custom_crud import create_and_connect_custom_integration
from app.services.integrations.integration_connection_service import connect_mcp_integration
from app.services.mcp.mcp_client import MCPClient
from app.services.mcp.mcp_oauth import build_oauth_auth_url
from app.utils.url_safety import CredentialsNeedHttpsError

INTEGRATION_ID = "custom-mcp-1"
USER_ID = "507f1f77bcf86cd799439011"
PUBLIC_HTTP = "http://93.184.216.34/mcp"
LAN_HTTP = "http://192.168.1.20/mcp"
REFUSAL = "has to start with https://"

_CONNECT = "app.services.integrations.integration_connection_service"
_CRUD = "app.services.integrations.custom_crud"


def _session_config(url: str, auth: str | None) -> dict[str, object]:
    return {"mcpServers": {INTEGRATION_ID: {"url": url, "auth": auth}}}


@pytest.mark.unit
class TestSessionAttach:
    """_build_config is where a stored token joins the session config."""

    @pytest.mark.parametrize(
        ("bearer", "oauth"), [("user-api-key", None), (None, "oauth-tok")], ids=["bearer", "oauth"]
    )
    async def test_a_token_is_never_attached_for_public_plain_http(
        self, monkeypatch: pytest.MonkeyPatch, bearer: str | None, oauth: str | None
    ) -> None:
        client = MCPClient(user_id=USER_ID)
        monkeypatch.setattr(client.token_store, "get_bearer_token", AsyncMock(return_value=bearer))
        monkeypatch.setattr(client.token_store, "get_oauth_token", AsyncMock(return_value=oauth))

        with pytest.raises(CredentialsNeedHttpsError, match=REFUSAL):
            await client._build_config(
                INTEGRATION_ID, MCPConfig(server_url=PUBLIC_HTTP, requires_auth=True)
            )

    @pytest.mark.parametrize("url", [LAN_HTTP, "https://mcp.example.com/mcp"])
    async def test_a_token_is_attached_over_https_or_the_lan(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        client = MCPClient(user_id=USER_ID)
        monkeypatch.setattr(
            client.token_store, "get_bearer_token", AsyncMock(return_value="user-api-key")
        )

        config = await client._build_config(INTEGRATION_ID, MCPConfig(server_url=url))

        assert config["mcpServers"][INTEGRATION_ID]["auth"] == "user-api-key"

    async def test_a_server_without_a_token_connects_over_public_plain_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MCPClient(user_id=USER_ID)
        monkeypatch.setattr(client.token_store, "get_bearer_token", AsyncMock(return_value=None))

        config = await client._build_config(INTEGRATION_ID, MCPConfig(server_url=PUBLIC_HTTP))

        assert config["mcpServers"][INTEGRATION_ID]["auth"] is None


@pytest.mark.unit
async def test_an_oauth_sign_in_never_starts_for_public_plain_http() -> None:
    resolved = MagicMock()
    resolved.mcp_config = MCPConfig(server_url=PUBLIC_HTTP, requires_auth=True)
    with (
        patch(
            "app.services.mcp.mcp_oauth.IntegrationResolver.resolve",
            AsyncMock(return_value=resolved),
        ),
        patch("app.services.mcp.mcp_oauth.discover_oauth_config", AsyncMock()) as discover,
        pytest.raises(CredentialsNeedHttpsError, match=REFUSAL),
    ):
        await build_oauth_auth_url(AsyncMock(), INTEGRATION_ID, "https://gaia.test/callback")

    discover.assert_not_awaited()


@pytest.mark.unit
class TestReconnect:
    @pytest.mark.parametrize(
        ("requires_auth", "bearer_token"),
        [(True, None), (False, "user-api-key")],
        ids=["oauth", "bearer"],
    )
    async def test_a_reconnect_to_public_plain_http_is_refused_with_the_https_message(
        self, requires_auth: bool, bearer_token: str | None
    ) -> None:
        mcp_client = AsyncMock()
        with (
            patch(f"{_CONNECT}.get_mcp_client", AsyncMock(return_value=mcp_client)),
            patch(f"{_CONNECT}.MCPTokenStore") as token_store,
            patch(f"{_CONNECT}.build_oauth_auth_url", AsyncMock()) as oauth_url,
        ):
            result = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id=INTEGRATION_ID,
                integration_name="Mine",
                requires_auth=requires_auth,
                redirect_path="/integrations",
                server_url=PUBLIC_HTTP,
                bearer_token=bearer_token,
            )

        assert result.status == "error"
        assert result.error == str(CredentialsNeedHttpsError())
        assert result.message == "This server needs an https:// URL to sign in."
        token_store.assert_not_called()
        oauth_url.assert_not_awaited()
        mcp_client.connect.assert_not_awaited()

    async def test_a_reconnect_to_a_lan_server_signs_in(self) -> None:
        with (
            patch(f"{_CONNECT}.get_mcp_client", AsyncMock(return_value=AsyncMock())),
            patch(f"{_CONNECT}.update_user_integration_status", AsyncMock()),
            patch(
                f"{_CONNECT}.build_oauth_auth_url", AsyncMock(return_value="https://as/authorize")
            ),
        ):
            result = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id=INTEGRATION_ID,
                integration_name="Mine",
                requires_auth=True,
                redirect_path="/integrations",
                server_url=LAN_HTTP,
            )

        assert (result.status, result.redirect_url) == ("redirect", "https://as/authorize")


@pytest.mark.unit
class TestAddCustomServer:
    @pytest.mark.parametrize(
        ("requires_auth", "bearer_token"),
        [(True, None), (False, "user-api-key")],
        ids=["oauth", "bearer"],
    )
    async def test_adding_a_signed_in_server_on_public_plain_http_is_refused_before_it_is_saved(
        self, requires_auth: bool, bearer_token: str | None
    ) -> None:
        request = CreateCustomIntegrationRequest(
            name="Mine",
            server_url=PUBLIC_HTTP,
            requires_auth=requires_auth,
            bearer_token=bearer_token,
        )
        with (
            patch(f"{_CRUD}.create_custom_integration", AsyncMock()) as create,
            pytest.raises(CredentialsNeedHttpsError, match=REFUSAL),
        ):
            await create_and_connect_custom_integration(USER_ID, request, AsyncMock())

        create.assert_not_awaited()

    async def test_a_server_found_to_need_oauth_on_public_plain_http_answers_the_https_message(
        self,
    ) -> None:
        integration = MagicMock()
        integration.integration_id = INTEGRATION_ID
        mcp_client = AsyncMock()
        mcp_client.probe_connection = AsyncMock(
            return_value={"requires_auth": True, "auth_type": "oauth"}
        )
        request = CreateCustomIntegrationRequest(name="Mine", server_url=PUBLIC_HTTP)
        with (
            patch(f"{_CRUD}._fetch_icon_safely", AsyncMock(return_value=None)),
            patch(f"{_CRUD}.create_custom_integration", AsyncMock(return_value=integration)),
            patch(
                f"{_CRUD}.build_oauth_auth_url",
                AsyncMock(side_effect=CredentialsNeedHttpsError()),
            ),
            patch(f"{_CRUD}.log") as log,
        ):
            _, result = await create_and_connect_custom_integration(USER_ID, request, mcp_client)

        assert result.status == "failed"
        assert result.error == str(CredentialsNeedHttpsError())
        log.warning.assert_called_once_with(
            f"{LogTag.INTEGRATION} Custom integration connect failed",
            error=str(CredentialsNeedHttpsError()),
            error_type="CredentialsNeedHttpsError",
            integration_id=INTEGRATION_ID,
        )
