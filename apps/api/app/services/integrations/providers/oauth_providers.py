"""The three OAuth-shaped transports, adapted to the provider interface.

These are thin on purpose: the connection logic already lives in
``integration_connection_service`` and is unchanged. All that happens here is
normalising three different call signatures into one, so the dispatch does not
have to know which arguments each transport wants.
"""

from __future__ import annotations

from typing import ClassVar

from app.models.integration_provider import ManagedBy
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.integrations.integration_connection_service import (
    McpConnectRequest,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
)
from app.services.integrations.providers.base import ConnectContext, IntegrationProvider


class McpIntegrationProvider(IntegrationProvider):
    """An MCP server — platform-configured or user-supplied."""

    managed_by: ClassVar[ManagedBy] = "mcp"

    async def connect(self, ctx: ConnectContext) -> ConnectIntegrationResponse:
        mcp_config = ctx.resolved.mcp_config
        return await connect_mcp_integration(
            McpConnectRequest(
                user_id=ctx.user_id,
                integration_id=ctx.integration_id,
                integration_name=ctx.resolved.name,
                requires_auth=ctx.resolved.requires_auth,
                redirect_path=ctx.redirect_path,
                server_url=mcp_config.server_url if mcp_config else None,
                is_platform=ctx.resolved.source == "platform",
                bearer_token=ctx.secret,
            )
        )


class ComposioIntegrationProvider(IntegrationProvider):
    """A connection brokered and hosted by Composio."""

    managed_by: ClassVar[ManagedBy] = "composio"

    async def connect(self, ctx: ConnectContext) -> ConnectIntegrationResponse:
        provider = ctx.provider_slug
        if not provider:
            return self.error(ctx, "Provider not configured")
        return await connect_composio_integration(
            user_id=ctx.user_id,
            integration_id=ctx.integration_id,
            integration_name=ctx.resolved.name,
            provider=provider,
            redirect_path=ctx.redirect_path,
        )


class SelfIntegrationProvider(IntegrationProvider):
    """An OAuth flow GAIA runs itself."""

    managed_by: ClassVar[ManagedBy] = "self"

    async def connect(self, ctx: ConnectContext) -> ConnectIntegrationResponse:
        provider = ctx.provider_slug
        if not provider:
            return self.error(ctx, "Provider not configured")
        return await connect_self_integration(
            user_id=ctx.user_id,
            user_email=ctx.user_email,
            integration_id=ctx.integration_id,
            integration_name=ctx.resolved.name,
            provider=provider,
            redirect_path=ctx.redirect_path,
        )
