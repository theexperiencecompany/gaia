"""Unit tests for the shared connect dispatch and the provider registry.

This is the single place a transport is chosen, for both the authenticated
endpoint and the login-free connect-link path. The behaviour that matters is
that every registered transport is reachable, an unregistered one fails
loudly, and no transport can leak an exception to the caller.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.cli_config import CliAuthSpec, CliConfig
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.integrations import connect_dispatch
from app.services.integrations.providers import (
    CliIntegrationProvider,
    ComposioIntegrationProvider,
    ConnectContext,
    McpIntegrationProvider,
    SelfIntegrationProvider,
    get_provider,
)

USER = "user-1"


def _resolved(
    managed_by: str = "mcp",
    *,
    source: str = "platform",
    available: bool = True,
    provider: str | None = "acme",
    cli_config: CliConfig | None = None,
) -> MagicMock:
    resolved = MagicMock()
    resolved.managed_by = managed_by
    resolved.source = source
    resolved.name = "Acme"
    resolved.requires_auth = False
    resolved.cli_config = cli_config
    resolved.mcp_config = MagicMock(server_url="https://mcp.example.test")
    if source == "platform":
        resolved.platform_integration = MagicMock(available=available, provider=provider)
    else:
        resolved.platform_integration = None
    return resolved


class TestProviderRegistry:
    @pytest.mark.parametrize(
        ("managed_by", "expected"),
        [
            ("mcp", McpIntegrationProvider),
            ("composio", ComposioIntegrationProvider),
            ("self", SelfIntegrationProvider),
            ("cli", CliIntegrationProvider),
        ],
    )
    def test_every_connectable_transport_is_registered(self, managed_by, expected):
        assert isinstance(get_provider(managed_by), expected)

    def test_internal_integrations_have_no_provider(self):
        # They are always on and have nothing to connect; the dispatch turns
        # this into a clear error rather than a crash.
        assert get_provider("internal") is None


class TestDispatch:
    async def test_unknown_integration_returns_none_for_a_404(self):
        with patch.object(
            connect_dispatch.IntegrationResolver, "resolve", AsyncMock(return_value=None)
        ):
            assert await connect_dispatch.initiate_integration_connection(USER, "nope") is None

    async def test_unavailable_platform_integration_is_rejected(self):
        with patch.object(
            connect_dispatch.IntegrationResolver,
            "resolve",
            AsyncMock(return_value=_resolved(available=False)),
        ):
            result = await connect_dispatch.initiate_integration_connection(USER, "x")
        assert result is not None
        assert result.status == "error"
        assert "not available" in (result.error or "")

    async def test_transport_without_a_provider_is_reported(self):
        with patch.object(
            connect_dispatch.IntegrationResolver,
            "resolve",
            AsyncMock(return_value=_resolved(managed_by="internal")),
        ):
            result = await connect_dispatch.initiate_integration_connection(USER, "todos")
        assert result is not None
        assert result.status == "error"
        assert "Unsupported integration type" in (result.error or "")

    async def test_provider_exceptions_never_escape(self):
        # The endpoint returns this straight to a client; an unhandled exception
        # here would be a 500 for something as ordinary as a dead MCP server.
        provider = MagicMock()
        provider.connect = AsyncMock(side_effect=RuntimeError("upstream exploded"))
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", AsyncMock(return_value=_resolved())
            ),
            patch.object(connect_dispatch, "get_provider", return_value=provider),
        ):
            result = await connect_dispatch.initiate_integration_connection(USER, "x")
        assert result is not None
        assert result.status == "error"
        assert "upstream exploded" in (result.error or "")

    async def test_a_completed_connection_is_recorded_once(self):
        provider = MagicMock()
        provider.connect = AsyncMock(
            return_value=ConnectIntegrationResponse(
                status="connected", integration_id="x", name="Acme"
            )
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", AsyncMock(return_value=_resolved())
            ),
            patch.object(connect_dispatch, "get_provider", return_value=provider),
            patch.object(connect_dispatch, "capture_context_event") as capture,
        ):
            await connect_dispatch.initiate_integration_connection(USER, "x")
        capture.assert_called_once()

    async def test_a_pending_connection_is_not_recorded_as_connected(self):
        provider = MagicMock()
        provider.connect = AsyncMock(
            return_value=ConnectIntegrationResponse(
                status="pending", integration_id="x", name="Acme"
            )
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", AsyncMock(return_value=_resolved())
            ),
            patch.object(connect_dispatch, "get_provider", return_value=provider),
            patch.object(connect_dispatch, "capture_context_event") as capture,
        ):
            await connect_dispatch.initiate_integration_connection(USER, "x")
        capture.assert_not_called()

    async def test_the_pasted_secret_reaches_the_provider(self):
        provider = MagicMock()
        provider.connect = AsyncMock(
            return_value=ConnectIntegrationResponse(
                status="pending", integration_id="x", name="Acme"
            )
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", AsyncMock(return_value=_resolved())
            ),
            patch.object(connect_dispatch, "get_provider", return_value=provider),
        ):
            await connect_dispatch.initiate_integration_connection(
                USER, "x", bearer_token="paste-me"
            )
        ctx: ConnectContext = provider.connect.await_args.args[0]
        assert ctx.secret == "paste-me"
        assert ctx.user_id == USER


class TestCliProvider:
    CONFIG = CliConfig(
        command="link-cli",
        install_command="npm install x",
        auth=CliAuthSpec(
            kind="device",
            login_command="link-cli auth login",
            verify_command="link-cli auth status",
        ),
    )

    def _ctx(self, cli_config: CliConfig | None) -> ConnectContext:
        return ConnectContext(
            user_id=USER,
            integration_id="stripe_link",
            resolved=_resolved(managed_by="cli", cli_config=cli_config),
            redirect_path="/integrations",
        )

    async def test_missing_configuration_is_an_error_not_a_crash(self):
        result = await CliIntegrationProvider().connect(self._ctx(None))
        assert result.status == "error"
        assert "no CLI configuration" in (result.error or "")

    @pytest.mark.parametrize(
        ("phase", "expected_status"),
        [
            ("installing", "pending"),
            ("awaiting_approval", "pending"),
            ("needs_token", "pending"),
            ("connected", "connected"),
            ("failed", "error"),
        ],
    )
    async def test_phase_maps_onto_the_shared_response_status(self, phase, expected_status):
        from app.services.cli.connect import CliConnectOutcome

        outcome = CliConnectOutcome(phase=phase, message="m", instructions="i")
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ):
            result = await CliIntegrationProvider().connect(self._ctx(self.CONFIG))
        assert result.status == expected_status
        assert result.cli is not None
        assert result.cli.phase == phase

    async def test_token_prompt_copy_is_carried_to_the_client(self):
        from app.services.cli.connect import CliConnectOutcome

        outcome = CliConnectOutcome(
            phase="needs_token", token_label="GitHub token", token_help_url="https://gh.test/t"
        )
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ):
            result = await CliIntegrationProvider().connect(self._ctx(self.CONFIG))
        assert result.cli is not None
        assert result.cli.token_label == "GitHub token"
        assert result.cli.token_help_url == "https://gh.test/t"
