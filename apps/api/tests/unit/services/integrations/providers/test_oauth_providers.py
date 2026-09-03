"""Unit tests for the OAuth-shaped provider adapters.

These adapters exist to turn three different call signatures into one, so what
matters is that each forwards the context to its underlying service correctly.
A silently wrong forward (the bearer token dropped, the wrong id passed as the
provider slug) would surface as a connect that fails for reasons the user
cannot act on.
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


def _ctx(
    *,
    managed_by: str = "mcp",
    source: str = "platform",
    provider: str | None = "acme",
    secret: str | None = None,
    requires_auth: bool = True,
) -> ConnectContext:
    resolved = MagicMock()
    resolved.managed_by = managed_by
    resolved.source = source
    resolved.name = "Acme"
    resolved.requires_auth = requires_auth
    resolved.mcp_config = MagicMock(server_url="https://mcp.example.test")
    resolved.platform_integration = MagicMock(provider=provider) if source == "platform" else None
    return ConnectContext(
        user_id=USER,
        integration_id="acme",
        resolved=resolved,
        redirect_path="/integrations",
        user_email="user@example.test",
        secret=secret,
    )


def _ok() -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(status="connected", integration_id="acme", name="Acme")


def _forwarded_request(connect: AsyncMock) -> McpConnectRequest:
    """The single request object the MCP transport was called with."""
    return connect.await_args.args[0]


class TestMcpProvider:
    async def test_forwards_the_server_url_and_platform_flag(self):
        with patch(f"{MODULE}.connect_mcp_integration", AsyncMock(return_value=_ok())) as connect:
            await McpIntegrationProvider().connect(_ctx())
        request = _forwarded_request(connect)
        assert request.server_url == "https://mcp.example.test"
        assert request.is_platform is True
        assert request.requires_auth is True

    async def test_a_custom_integration_is_not_marked_platform(self):
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


class TestComposioProvider:
    async def test_forwards_the_provider_slug(self):
        with patch(
            f"{MODULE}.connect_composio_integration", AsyncMock(return_value=_ok())
        ) as connect:
            await ComposioIntegrationProvider().connect(_ctx(managed_by="composio"))
        assert connect.await_args.kwargs["provider"] == "acme"

    @pytest.mark.parametrize("provider", [None, ""])
    async def test_a_missing_provider_is_an_error_not_a_call(self, provider):
        with patch(
            f"{MODULE}.connect_composio_integration", AsyncMock(return_value=_ok())
        ) as connect:
            result = await ComposioIntegrationProvider().connect(
                _ctx(managed_by="composio", provider=provider)
            )
        connect.assert_not_awaited()
        assert result.status == "error"
        assert "Provider not configured" in (result.error or "")


class TestSelfProvider:
    async def test_forwards_the_email_as_the_oauth_login_hint(self):
        with patch(f"{MODULE}.connect_self_integration", AsyncMock(return_value=_ok())) as connect:
            await SelfIntegrationProvider().connect(_ctx(managed_by="self"))
        assert connect.await_args.kwargs["user_email"] == "user@example.test"

    async def test_a_missing_provider_is_an_error_not_a_call(self):
        with patch(f"{MODULE}.connect_self_integration", AsyncMock(return_value=_ok())) as connect:
            result = await SelfIntegrationProvider().connect(_ctx(managed_by="self", provider=None))
        connect.assert_not_awaited()
        assert result.status == "error"


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
