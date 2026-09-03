"""Unit tests for the OAuth-shaped provider adapters.

These adapters exist to turn three different call signatures into one, so what
matters is that each forwards the context to its underlying service correctly.
A silently wrong forward (the bearer token dropped, the wrong id passed as the
provider slug) would surface as a connect that fails for reasons the user
cannot act on — which is why the forwarded call is asserted whole rather than
field by field: a dropped argument is exactly as broken as a wrong one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.integrations.integration_connection_service import McpConnectRequest
from app.services.integrations.providers import (
    ComposioIntegrationProvider,
    ConnectContext,
    McpIntegrationProvider,
    SelfIntegrationProvider,
)

MODULE = "app.services.integrations.providers.oauth_providers"
USER = "user-1"
# Deliberately different from the provider slug below: an integration id and
# the upstream provider it is brokered through are separate values, and a
# transport that confused them would still look right if they matched.
INTEGRATION = "acme-crm"
PROVIDER = "acme"


def _ctx(
    *,
    managed_by: str = "mcp",
    source: str = "platform",
    provider: str | None = PROVIDER,
    secret: str | None = None,
    requires_auth: bool = True,
) -> ConnectContext:
    resolved = MagicMock()
    resolved.managed_by = managed_by
    resolved.source = source
    resolved.name = "Acme CRM"
    resolved.requires_auth = requires_auth
    resolved.mcp_config = MagicMock(server_url="https://mcp.example.test")
    resolved.platform_integration = MagicMock(provider=provider) if source == "platform" else None
    return ConnectContext(
        user_id=USER,
        integration_id=INTEGRATION,
        resolved=resolved,
        redirect_path="/integrations",
        user_email="user@example.test",
        secret=secret,
    )


def _resolved(*, source: str = "platform") -> MagicMock:
    """The catalog resolution a disconnect is handed."""
    resolved = MagicMock()
    resolved.integration_id = INTEGRATION
    resolved.source = source
    resolved.name = "Acme CRM"
    return resolved


def _ok() -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(status="connected", integration_id=INTEGRATION, name="Acme")


def _forwarded_request(connect: AsyncMock) -> McpConnectRequest:
    """The single request object the MCP transport was called with."""
    return connect.await_args.args[0]


class TestMcpProvider:
    async def test_the_whole_context_reaches_the_mcp_connect_request(self):
        # Everything the MCP flow branches on lives in this one object: the URL
        # it probes, whether it may fall back to platform credentials, and
        # whether it has to ask for auth at all.
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=_ok())) as connect:
            await McpIntegrationProvider().connect(_ctx(secret="paste-me"))
        assert _forwarded_request(connect) == McpConnectRequest(
            user_id=USER,
            integration_id=INTEGRATION,
            integration_name="Acme CRM",
            requires_auth=True,
            redirect_path="/integrations",
            server_url="https://mcp.example.test",
            is_platform=True,
            bearer_token="paste-me",
        )

    async def test_a_custom_integration_is_not_marked_platform(self):
        # Platform MCP servers may use GAIA's own credentials; a user's own
        # server must never be handed them.
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=_ok())) as connect:
            await McpIntegrationProvider().connect(_ctx(source="custom"))
        assert _forwarded_request(connect).is_platform is False

    async def test_the_pasted_secret_is_forwarded_as_the_bearer_token(self):
        # Dropping it here would send the user back to a token dialog that
        # already has their token.
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=_ok())) as connect:
            await McpIntegrationProvider().connect(_ctx(secret="paste-me"))
        assert _forwarded_request(connect).bearer_token == "paste-me"

    async def test_a_missing_mcp_config_forwards_no_url_rather_than_raising(self):
        ctx = _ctx()
        ctx.resolved.mcp_config = None
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=_ok())) as connect:
            await McpIntegrationProvider().connect(ctx)
        assert _forwarded_request(connect).server_url is None

    async def test_the_transports_answer_is_returned_unchanged(self):
        response = _ok()
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=response)):
            result = await McpIntegrationProvider().connect(_ctx())
        assert result is response


class TestComposioProvider:
    async def test_the_whole_context_reaches_composio(self):
        with patch(
            f"{MODULE}.connect_composio_integration", AsyncMock(return_value=_ok())
        ) as connect:
            await ComposioIntegrationProvider().connect(_ctx(managed_by="composio"))
        assert connect.await_args.kwargs == {
            "user_id": USER,
            "integration_id": INTEGRATION,
            "integration_name": "Acme CRM",
            "provider": PROVIDER,
            "redirect_path": "/integrations",
        }

    @pytest.mark.parametrize("provider", [None, ""])
    async def test_a_missing_provider_is_an_error_not_a_call(self, provider):
        # Composio is keyed entirely on the slug; calling it without one would
        # start a connection against whatever Composio defaults to.
        with patch(
            f"{MODULE}.connect_composio_integration", AsyncMock(return_value=_ok())
        ) as connect:
            result = await ComposioIntegrationProvider().connect(
                _ctx(managed_by="composio", provider=provider)
            )
        connect.assert_not_awaited()
        assert result.status == "error"
        assert result.error == "Provider not configured"


class TestSelfProvider:
    async def test_the_whole_context_reaches_the_self_hosted_oauth_flow(self):
        # ``user_email`` is the OAuth login hint: without it Google shows an
        # account chooser instead of the account the user is signed in as.
        with patch(f"{MODULE}.connect_self_integration", AsyncMock(return_value=_ok())) as connect:
            await SelfIntegrationProvider().connect(_ctx(managed_by="self"))
        assert connect.await_args.kwargs == {
            "user_id": USER,
            "user_email": "user@example.test",
            "integration_id": INTEGRATION,
            "integration_name": "Acme CRM",
            "provider": PROVIDER,
            "redirect_path": "/integrations",
        }

    async def test_a_missing_provider_is_an_error_not_a_call(self):
        with patch(f"{MODULE}.connect_self_integration", AsyncMock(return_value=_ok())) as connect:
            result = await SelfIntegrationProvider().connect(_ctx(managed_by="self", provider=None))
        connect.assert_not_awaited()
        assert result.status == "error"
        assert result.error == "Provider not configured"


class TestMcpDisconnect:
    """Disconnecting an MCP server is three writes, and which of them run
    depends on who owns the server.

    A platform server is shared by every user, so only the caller's link may go.
    A server the caller added themselves is theirs alone, so its catalog
    document goes with it — otherwise the marketplace keeps an entry nobody
    owns and nobody can remove.
    """

    async def test_a_custom_server_loses_its_session_link_and_catalog_row(self):
        resolved = _resolved(source="custom")
        mcp_client = MagicMock()
        mcp_client.disconnect = AsyncMock()
        with (
            patch(f"{MODULE}.get_mcp_client", AsyncMock(return_value=mcp_client)) as get_client,
            patch(f"{MODULE}.remove_user_integration", AsyncMock()) as remove,
            patch(f"{MODULE}.delete_if_user_authored", AsyncMock()) as delete,
        ):
            await McpIntegrationProvider().disconnect(USER, resolved)

        # The session is per user, so it is that user's client that must drop it.
        get_client.assert_awaited_once_with(user_id=USER)
        mcp_client.disconnect.assert_awaited_once_with(INTEGRATION)
        remove.assert_awaited_once_with(USER, INTEGRATION)
        delete.assert_awaited_once_with(USER, resolved)

    async def test_a_platform_server_keeps_its_catalog_row(self):
        # Deleting it would remove a shared integration from every other user's
        # marketplace because one person disconnected.
        resolved = _resolved(source="platform")
        mcp_client = MagicMock()
        mcp_client.disconnect = AsyncMock()
        with (
            patch(f"{MODULE}.get_mcp_client", AsyncMock(return_value=mcp_client)),
            patch(f"{MODULE}.remove_user_integration", AsyncMock()) as remove,
            patch(f"{MODULE}.delete_if_user_authored", AsyncMock()) as delete,
        ):
            await McpIntegrationProvider().disconnect(USER, resolved)

        remove.assert_awaited_once_with(USER, INTEGRATION)
        delete.assert_not_awaited()


class TestProviderIdentity:
    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            (McpIntegrationProvider, "mcp"),
            (ComposioIntegrationProvider, "composio"),
            (SelfIntegrationProvider, "self"),
        ],
    )
    def test_each_adapter_declares_the_transport_it_serves(self, provider, expected):
        # The registry is keyed on this; a wrong value silently shadows another
        # transport or leaves one unreachable.
        assert provider.managed_by == expected
