"""Brutal behavior tests for the connect dispatcher.

Targets ``resolve_and_connect_integration`` / ``build_connect_url`` — the single
source of truth that the /connect endpoint, the connect_integration tool, and
the handoff/checker prompts all route through. The connectors and the resolver
are mocked at the boundary (DB / external OAuth); the dispatch logic itself is
the code under test.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.integrations.responses import ConnectIntegrationResponse
import app.services.integrations.integration_connection_service as svc
from app.services.integrations.integration_connection_service import (
    build_connect_url,
    resolve_and_connect_integration,
)


def _resolved(
    managed_by: str,
    *,
    name: str = "Gmail",
    source: str = "platform",
    available: bool = True,
    provider: str | None = "google",
    requires_auth: bool = True,
    has_mcp: bool = False,
) -> SimpleNamespace:
    """A stand-in for ResolvedIntegration with the attributes the dispatcher reads."""
    platform = (
        SimpleNamespace(available=available, provider=provider) if source == "platform" else None
    )
    mcp = (
        SimpleNamespace(server_url="https://mcp.example.com", requires_auth=requires_auth)
        if has_mcp
        else None
    )
    return SimpleNamespace(
        name=name,
        source=source,
        managed_by=managed_by,
        requires_auth=requires_auth,
        platform_integration=platform,
        mcp_config=mcp,
    )


def _redirect(url: str = "https://connect.example.com/oauth") -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(
        status="redirect", integration_id="gmail", name="Gmail", redirect_url=url
    )


@pytest.mark.unit
class TestResolveAndConnectIntegration:
    async def test_unknown_integration_returns_none(self) -> None:
        with patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=None)):
            assert await resolve_and_connect_integration("u1", "ghost") is None

    async def test_unavailable_platform_returns_error_without_dispatch(self) -> None:
        resolved = _resolved("composio", available=False)
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(svc, "connect_composio_integration", new_callable=AsyncMock) as mock_c,
        ):
            result = await resolve_and_connect_integration("u1", "gmail")
        assert result is not None
        assert result.status == "error"
        assert "not available" in (result.error or "")
        assert result.integration_id == "gmail"
        mock_c.assert_not_awaited()

    async def test_mcp_routes_with_resolved_args(self) -> None:
        resolved = _resolved("mcp", source="custom", has_mcp=True, requires_auth=True)
        canned = _redirect("https://mcp.example.com/oauth")
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc, "connect_mcp_integration", new_callable=AsyncMock, return_value=canned
            ) as mock_mcp,
        ):
            result = await resolve_and_connect_integration(
                "u1", "custom-mcp", bearer_token="tok", redirect_path="/chat"
            )
        assert result is canned
        kwargs = mock_mcp.await_args.kwargs
        assert kwargs["requires_auth"] is True
        assert kwargs["server_url"] == "https://mcp.example.com"
        assert kwargs["is_platform"] is False  # source == "custom"
        assert kwargs["bearer_token"] == "tok"
        assert kwargs["redirect_path"] == "/chat"

    async def test_composio_missing_provider_errors_without_calling_connector(self) -> None:
        resolved = _resolved("composio", provider=None)
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(svc, "connect_composio_integration", new_callable=AsyncMock) as mock_c,
        ):
            result = await resolve_and_connect_integration("u1", "gmail")
        assert result is not None and result.status == "error"
        assert "Provider not configured" in (result.error or "")
        mock_c.assert_not_awaited()

    async def test_self_threads_user_email_to_connector(self) -> None:
        """The user_email we added must reach connect_self_integration (Google login hint)."""
        resolved = _resolved("self", provider="google")
        canned = _redirect()
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc, "connect_self_integration", new_callable=AsyncMock, return_value=canned
            ) as mock_self,
        ):
            result = await resolve_and_connect_integration(
                "u1", "gmail", user_email="me@example.com"
            )
        assert result is canned
        assert mock_self.await_args.kwargs["user_email"] == "me@example.com"
        assert mock_self.await_args.kwargs["provider"] == "google"

    async def test_unsupported_managed_by_returns_error(self) -> None:
        resolved = _resolved("carrier-pigeon")
        with patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)):
            result = await resolve_and_connect_integration("u1", "gmail")
        assert result is not None and result.status == "error"
        assert "carrier-pigeon" in (result.error or "")

    async def test_connector_exception_is_swallowed_into_error_response(self) -> None:
        """A connector blowing up (network/Redis) must degrade to status=error,
        never propagate — every prompt site relies on this."""
        resolved = _resolved("self", provider="google")
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc,
                "connect_self_integration",
                new_callable=AsyncMock,
                side_effect=ValueError("oauth state store down"),
            ),
        ):
            result = await resolve_and_connect_integration("u1", "gmail")
        assert result is not None
        assert result.status == "error"
        assert "oauth state store down" in (result.error or "")


@pytest.mark.unit
class TestBuildConnectUrl:
    async def test_returns_redirect_url(self) -> None:
        resolved = _resolved("self", provider="google")
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc,
                "connect_self_integration",
                new_callable=AsyncMock,
                return_value=_redirect("https://accounts.google.com/o/oauth2/auth"),
            ),
        ):
            url = await build_connect_url("u1", "gmail", user_email="me@example.com")
        assert url == "https://accounts.google.com/o/oauth2/auth"

    async def test_returns_none_when_already_connected(self) -> None:
        """A 'connected' response carries no redirect_url — must yield None, not crash."""
        resolved = _resolved("mcp", source="custom", has_mcp=True)
        connected = ConnectIntegrationResponse(
            status="connected", integration_id="gmail", name="Gmail", tools_count=3
        )
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc, "connect_mcp_integration", new_callable=AsyncMock, return_value=connected
            ),
        ):
            assert await build_connect_url("u1", "gmail") is None

    async def test_returns_none_on_error(self) -> None:
        resolved = _resolved("self", provider="google")
        with (
            patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(
                svc,
                "connect_self_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            assert await build_connect_url("u1", "gmail") is None

    async def test_returns_none_for_unknown_integration(self) -> None:
        with patch.object(svc.IntegrationResolver, "resolve", AsyncMock(return_value=None)):
            assert await build_connect_url("u1", "ghost") is None
