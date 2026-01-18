"""Integration connection service - handles connect/disconnect logic."""

from functools import lru_cache
from typing import Literal

from mcp_use.exceptions import OAuthAuthenticationError

from app.config.loggers import auth_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_scopes
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url, invalidate_mcp_status_cache
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationConfigItem,
    IntegrationsConfigResponse,
    IntegrationSuccessResponse,
)
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.integration_service import (
    delete_custom_integration,
    remove_user_integration,
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.oauth.oauth_state_service import create_oauth_state
from app.utils.oauth_utils import build_google_oauth_url


@lru_cache(maxsize=1)
def build_integrations_config() -> IntegrationsConfigResponse:
    """Build cached integrations configuration response."""
    integration_configs = []
    for integration in OAUTH_INTEGRATIONS:
        if integration.managed_by == "internal":
            continue

        # Cast to Literal type for mypy
        auth_type_literal: Literal["none", "oauth", "bearer"] | None = None
        if integration.mcp_config:
            auth_type_literal = (
                "oauth" if integration.mcp_config.requires_auth else "none"
            )

        integration_configs.append(
            IntegrationConfigItem(
                id=integration.id,
                name=integration.name,
                description=integration.description,
                category=integration.category,
                provider=integration.provider,
                available=integration.available,
                is_special=integration.is_special,
                display_priority=integration.display_priority,
                included_integrations=integration.included_integrations,
                is_featured=integration.is_featured,
                managed_by=integration.managed_by,
                auth_type=auth_type_literal,
            )
        )
    return IntegrationsConfigResponse(integrations=integration_configs)


async def connect_mcp_integration(
    user_id: str,
    integration_id: str,
    requires_auth: bool,
    redirect_path: str,
    server_url: str | None = None,
    is_platform: bool = False,
    probe_result: dict | None = None,
) -> ConnectIntegrationResponse:
    """Handle MCP integration connection.

    Args:
        probe_result: Optional pre-fetched probe result to avoid redundant probing.
                      If provided, skips internal probe_connection() call.
    """
    mcp_client = await get_mcp_client(user_id=user_id)

    # Use provided probe_result or perform probe if needed
    if server_url and not requires_auth and probe_result is None:
        probe_result = await mcp_client.probe_connection(server_url)

    # Check if probe detected auth requirement
    if probe_result and not requires_auth and probe_result.get("requires_auth"):
        logger.info(f"Probe detected OAuth for {integration_id}")
        requires_auth = True
        # Update MongoDB with discovered auth requirements
        auth_type = probe_result.get("auth_type", "oauth")
        await mcp_client.update_integration_auth_status(
            integration_id, requires_auth=True, auth_type=auth_type
        )

    if requires_auth:
        if not is_platform:
            await update_user_integration_status(user_id, integration_id, "created")

        auth_url = await mcp_client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path=redirect_path,
            challenge_data=probe_result,  # Pass probe result to avoid re-discovery
        )

        return ConnectIntegrationResponse(
            status="redirect",
            integration_id=integration_id,
            redirect_url=auth_url,
            message="OAuth authentication required",
        )

    try:
        tools = await mcp_client.connect(integration_id)
    except OAuthAuthenticationError:
        # Server requires OAuth - redirect to OAuth flow
        logger.info(f"Connection got auth error, triggering OAuth for {integration_id}")
        if not is_platform:
            await update_user_integration_status(user_id, integration_id, "created")

        auth_url = await mcp_client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path=redirect_path,
            # No probe_result here - connection failed, need fresh discovery
        )
        return ConnectIntegrationResponse(
            status="redirect",
            integration_id=integration_id,
            redirect_url=auth_url,
            message="OAuth authentication required",
        )

    tools_count = len(tools) if tools else 0

    await invalidate_mcp_status_cache(user_id)

    # Subagent indexing handled in MCPClient._handle_custom_integration_connect

    return ConnectIntegrationResponse(
        status="connected",
        integration_id=integration_id,
        tools_count=tools_count,
        message="Integration connected successfully",
    )


async def connect_composio_integration(
    user_id: str,
    integration_id: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle Composio integration connection."""
    composio_service = get_composio_service()

    state_token = await create_oauth_state(
        user_id=user_id,
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    await update_user_integration_status(user_id, integration_id, "created")

    url = await composio_service.connect_account(
        provider, user_id, state_token=state_token
    )

    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        redirect_url=url["redirect_url"],
        message="OAuth authentication required",
    )


async def connect_self_integration(
    user_id: str,
    user_email: str,
    integration_id: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle self-managed integration connection (Google)."""
    if provider != "google":
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            error=f"Provider {provider} not implemented",
        )

    state_token = await create_oauth_state(
        user_id=user_id,
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    await update_user_integration_status(user_id, integration_id, "created")

    auth_url = await build_google_oauth_url(
        user_email=user_email,
        state_token=state_token,
        integration_scopes=get_integration_scopes(integration_id),
        user_id=user_id,
    )

    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        redirect_url=auth_url,
        message="OAuth authentication required",
    )


async def disconnect_integration(
    user_id: str, integration_id: str
) -> IntegrationSuccessResponse:
    """Disconnect an integration for the user."""
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        raise ValueError(f"Integration {integration_id} not found")

    if resolved.source == "custom":
        mcp_client = await get_mcp_client(user_id=user_id)
        await mcp_client.disconnect(integration_id)
        await remove_user_integration(user_id, integration_id)
        if resolved.custom_doc and resolved.custom_doc.get("created_by") == user_id:
            await delete_custom_integration(user_id, integration_id)

    elif resolved.managed_by == "composio":
        composio_service = get_composio_service()
        provider = (
            resolved.platform_integration.provider
            if resolved.platform_integration
            else None
        )
        if not provider:
            raise ValueError(f"Provider not configured for {integration_id}")
        await composio_service.delete_connected_account(
            user_id=user_id, provider=provider
        )

    elif resolved.managed_by == "self":
        provider = (
            resolved.platform_integration.provider
            if resolved.platform_integration
            else None
        )
        if not provider:
            raise ValueError(f"Provider not configured for {integration_id}")
        await token_repository.revoke_token(user_id=user_id, provider=provider)

    elif resolved.managed_by == "mcp":
        mcp_client = await get_mcp_client(user_id=user_id)
        await mcp_client.disconnect(integration_id)
        await remove_user_integration(user_id, integration_id)

    else:
        raise ValueError(f"Integration {integration_id} disconnect not supported")

    await _invalidate_caches(user_id, integration_id, resolved.managed_by)

    return IntegrationSuccessResponse(
        message=f"Successfully disconnected {resolved.name}",
        integration_id=integration_id,
    )


async def _invalidate_caches(
    user_id: str, integration_id: str, managed_by: str
) -> None:
    """Invalidate relevant caches after disconnect."""
    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"OAuth status cache invalidated for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate OAuth status cache: {e}")

    if managed_by != "mcp":
        try:
            await update_user_integration_status(user_id, integration_id, "created")
            logger.info(f"Updated status to 'created' for {integration_id}")
        except Exception as e:
            logger.warning(f"Failed to update status: {e}")
