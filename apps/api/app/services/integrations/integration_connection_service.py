"""Integration connection service - handles connect/disconnect logic."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from mcp_use.client.exceptions import OAuthAuthenticationError
import pymongo.errors
import redis

from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_integration_scopes,
)
from app.config.token_repository import token_repository
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.models.mcp_config import McpAuthChallenge, McpProbeResult
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationConfigItem,
    IntegrationsConfigResponse,
    IntegrationSuccessResponse,
)
from app.services.cli import disconnect as cli_disconnect
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.custom_crud import delete_custom_integration
from app.services.integrations.integration_resolver import (
    IntegrationResolver,
    ResolvedIntegration,
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.integrations.user_integrations import (
    invalidate_user_integration_caches,
    remove_user_integration,
)
from app.services.integrations_fs import schedule_user_integrations_sync
from app.services.mcp.mcp_client import MCPClient, get_mcp_client
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_state_service import create_oauth_state
from app.utils.oauth_utils import build_google_oauth_url
from shared.py.wide_events import log


@lru_cache(maxsize=1)
def build_integrations_config() -> IntegrationsConfigResponse:
    """Build cached integrations configuration response."""
    integration_configs = []
    for integration in OAUTH_INTEGRATIONS:
        if integration.managed_by == "internal":
            continue

        auth_type_literal: Literal["none", "oauth", "bearer"] | None = None
        if integration.mcp_config:
            # Honour an explicitly configured auth_type (e.g. "bearer" for
            # API-key servers like Browserbase); otherwise derive from requires_auth.
            auth_type_literal = integration.mcp_config.auth_type or (
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
                # A CLI declares its auth shape in cli_config, not mcp_config;
                # without this every CLI integration renders as "no sign-in
                # needed" and the connect dialog looks like a no-op.
                requires_auth=(
                    integration.mcp_config.requires_auth
                    if integration.mcp_config
                    else (
                        integration.cli_config.auth.kind != "none"
                        if integration.cli_config
                        else False
                    )
                ),
                slug=integration.id,  # Platform integrations use ID as slug
            )
        )
    return IntegrationsConfigResponse(integrations=integration_configs)


async def _redirect_to_oauth(
    mcp_client: MCPClient,
    integration_id: str,
    integration_name: str,
    redirect_path: str,
    challenge_data: McpAuthChallenge | None = None,
) -> ConnectIntegrationResponse:
    """Build the provider OAuth URL and wrap it in a redirect response."""
    auth_url = await mcp_client.build_oauth_auth_url(
        integration_id=integration_id,
        redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
        redirect_path=redirect_path,
        challenge_data=challenge_data,
    )
    log.set(
        integration={
            "provider": integration_name,
            "action": "connect_mcp",
            "status": "redirect",
            "auth_type": "oauth",
        }
    )
    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        name=integration_name,
        redirect_url=auth_url,
        message="OAuth authentication required",
    )


@dataclass(frozen=True)
class McpConnectRequest:
    """One attempt to connect an MCP-backed integration.

    A single request rather than nine parameters threaded through four helpers:
    every step of the flow needs the same identity (user, integration, display
    name) plus the same handful of knobs, and re-listing them at each hop is how
    a helper ends up reading `is_platform` from one call site and not the other.
    """

    user_id: str
    integration_id: str
    integration_name: str
    requires_auth: bool
    redirect_path: str
    server_url: str | None = None
    is_platform: bool = False
    probe_result: McpProbeResult | None = None
    bearer_token: str | None = None


async def _handle_auth_required(
    request: McpConnectRequest,
    mcp_client: MCPClient,
    *,
    detected_auth_type: str | None,
    probe_result: McpProbeResult | None,
) -> ConnectIntegrationResponse:
    """Bearer servers return bearer_required (frontend collects a key); everything
    else gets the OAuth redirect."""
    if not request.is_platform:
        await update_user_integration_status(request.user_id, request.integration_id, "created")

    if detected_auth_type == "bearer":
        return ConnectIntegrationResponse(
            status="error",
            integration_id=request.integration_id,
            name=request.integration_name,
            error="bearer_required",
            message="This integration requires an API key.",
        )

    # The WWW-Authenticate challenge lives under `oauth_challenge`, not at the top
    # level of the probe result — passing the whole result meant discovery saw none
    # of the challenge keys, dropped `initial_scope`, and re-fetched the PRM it was
    # given. Typing both ends surfaced it.
    return await _redirect_to_oauth(
        mcp_client,
        request.integration_id,
        request.integration_name,
        request.redirect_path,
        challenge_data=probe_result.get("oauth_challenge") if probe_result else None,
    )


async def _handle_connect_failure(
    request: McpConnectRequest, error: Exception
) -> ConnectIntegrationResponse:
    """Surface a connection failure as a structured error, never a 500."""
    if not request.is_platform:
        await update_user_integration_status(request.user_id, request.integration_id, "created")
    log.warning(
        f"{LogTag.INTEGRATION} MCP connection failed for",
        integration_id=request.integration_id,
        error=error,
        user_id=request.user_id,
    )
    log.set(
        integration={
            "provider": request.integration_name,
            "action": "connect_mcp",
            "status": "error",
        }
    )
    return ConnectIntegrationResponse(
        status="error",
        integration_id=request.integration_id,
        name=request.integration_name,
        error=str(error),
        message="Connection failed",
    )


async def connect_mcp_integration(request: McpConnectRequest) -> ConnectIntegrationResponse:
    """Handle MCP integration connection."""
    log.set(integration={"provider": request.integration_name, "action": "connect_mcp"})
    mcp_client = await get_mcp_client(user_id=request.user_id)

    # Bearer token flow - store and connect directly
    if request.bearer_token:
        return await _connect_with_bearer_token(request, request.bearer_token, mcp_client)

    # Use provided probe_result or perform probe if needed
    probe_result = request.probe_result
    requires_auth = request.requires_auth
    if request.server_url and not requires_auth and probe_result is None:
        probe_result = await mcp_client.probe_connection(request.server_url)

    # Check if probe detected auth requirement
    detected_auth_type: str | None = None
    if probe_result and not requires_auth and probe_result.get("requires_auth"):
        detected_auth_type = probe_result.get("auth_type", "oauth")
        await mcp_client.update_integration_auth_status(
            request.integration_id, requires_auth=True, auth_type=detected_auth_type
        )
        requires_auth = True

    if requires_auth:
        return await _handle_auth_required(
            request,
            mcp_client,
            detected_auth_type=detected_auth_type,
            probe_result=probe_result,
        )

    try:
        tools = await mcp_client.connect(request.integration_id)
    except OAuthAuthenticationError:
        # mcp-use only learned auth was needed at connect time — route to OAuth.
        return await _handle_auth_required(
            request, mcp_client, detected_auth_type=None, probe_result=None
        )
    except Exception as e:
        return await _handle_connect_failure(request, e)

    tools_count = len(tools) if tools else 0
    await invalidate_user_integration_caches(request.user_id)

    log.set(
        integration={
            "provider": request.integration_name,
            "action": "connect_mcp",
            "status": "connected",
            # Reached only on the no-token path; the bearer flow returns above.
            "auth_type": "none",
            "tools_count": tools_count,
        }
    )
    return ConnectIntegrationResponse(
        status="connected",
        integration_id=request.integration_id,
        name=request.integration_name,
        tools_count=tools_count,
        message="Integration connected successfully",
    )


async def _connect_with_bearer_token(
    request: McpConnectRequest, bearer_token: str, mcp_client: MCPClient
) -> ConnectIntegrationResponse:
    """Store bearer token and attempt connection."""
    token_store = MCPTokenStore(request.user_id)
    await token_store.store_bearer_token(request.integration_id, bearer_token)

    try:
        tools = await mcp_client.connect(request.integration_id)
        # Busts the full per-user integration cache set (status + tools:user:*).
        await update_user_integration_status(request.user_id, request.integration_id, "connected")
        tools_count = len(tools) if tools else 0
        log.set(
            integration={
                "provider": request.integration_name,
                "action": "connect_mcp",
                "auth_type": "bearer",
                "status": "connected",
                "tools_count": tools_count,
            }
        )
        return ConnectIntegrationResponse(
            status="connected",
            integration_id=request.integration_id,
            name=request.integration_name,
            tools_count=tools_count,
            message="Integration connected successfully",
        )
    except Exception as e:
        # Rollback: clean up stored credentials on connection failure
        await token_store.delete_credentials(request.integration_id)
        await invalidate_user_integration_caches(request.user_id)
        log.set(
            integration={
                "provider": request.integration_name,
                "action": "connect_mcp",
                "auth_type": "bearer",
                "status": "error",
            }
        )
        return ConnectIntegrationResponse(
            status="error",
            integration_id=request.integration_id,
            name=request.integration_name,
            error=str(e),
            message="Connection failed",
        )


async def connect_composio_integration(
    user_id: str,
    integration_id: str,
    integration_name: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle Composio integration connection."""
    log.set(integration={"provider": provider, "action": "connect_composio"})
    composio_service = get_composio_service()

    state_token = await create_oauth_state(
        user_id=user_id,
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    await update_user_integration_status(user_id, integration_id, "created")

    url = await composio_service.connect_account(provider, user_id, state_token=state_token)

    # Composio mints the connected account at initiate time, before the user has
    # authorized it. Record the id now so a connection abandoned mid-flow is still
    # addressable; the callback overwrites it with whichever account actually
    # completed.
    await update_user_integration_status(
        user_id, integration_id, "created", connected_account_id=url["connection_id"]
    )

    log.set(
        integration={
            "provider": provider,
            "action": "connect_composio",
            "managed_by": "composio",
            "auth_type": "oauth2",
            "status": "redirect",
        }
    )
    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        name=integration_name,
        redirect_url=url["redirect_url"],
        message="OAuth authentication required",
    )


async def connect_self_integration(
    user_id: str,
    user_email: str,
    integration_id: str,
    integration_name: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle self-managed integration connection (Google)."""
    log.set(integration={"provider": provider, "action": "connect_self"})
    if provider != "google":
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            name=integration_name,
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

    log.set(
        integration={
            "provider": provider,
            "action": "connect_self",
            "managed_by": "self",
            "auth_type": "oauth2",
            "status": "redirect",
        }
    )
    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        name=integration_name,
        redirect_url=auth_url,
        message="OAuth authentication required",
    )


def _require_provider(resolved: ResolvedIntegration) -> str:
    """The upstream provider slug, or a loud failure.

    Composio and the self-managed OAuth flow both revoke by provider, and a
    catalog entry missing one cannot be torn down at all — better a raised
    ValueError than a silent no-op that leaves the grant live upstream.
    """
    provider = resolved.platform_integration.provider if resolved.platform_integration else None
    if not provider:
        raise ValueError(f"Provider not configured for {resolved.integration_id}")
    return provider


async def _delete_if_user_authored(user_id: str, resolved: ResolvedIntegration) -> None:
    """Drop the catalog document too, but only for the user who authored it.

    A custom integration cloned from someone else's is removed from this user
    without deleting the original.
    """
    if (
        resolved.source == "custom"
        and resolved.custom_doc
        and resolved.custom_doc.get("created_by") == user_id
    ):
        await delete_custom_integration(user_id, resolved.integration_id)


async def _disconnect_cli(user_id: str, resolved: ResolvedIntegration) -> None:
    """Tear down the CLI's sandbox state, then detach it from the user."""
    # `cli_config` is pinned by the catalog validator for this transport.
    if resolved.cli_config:
        try:
            await cli_disconnect(user_id, resolved.integration_id, resolved.cli_config)
        except Exception as e:
            # Best-effort cleanup: the durable HOME is per-integration and is
            # recreated on the next connect anyway. Letting an unreachable
            # sandbox abort the disconnect would leave the user owning an
            # integration they cannot remove until it comes back.
            log.warning(
                f"{LogTag.INTEGRATION} CLI teardown failed; removing the record anyway",
                integration_id=resolved.integration_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
    await remove_user_integration(user_id, resolved.integration_id)
    await _delete_if_user_authored(user_id, resolved)


async def _disconnect_mcp(user_id: str, resolved: ResolvedIntegration) -> None:
    """Drop the MCP session and the user's record of the server."""
    mcp_client = await get_mcp_client(user_id=user_id)
    await mcp_client.disconnect(resolved.integration_id)
    await remove_user_integration(user_id, resolved.integration_id)


async def _disconnect_custom_mcp(user_id: str, resolved: ResolvedIntegration) -> None:
    """An MCP server the user added themselves: also drop the catalog document."""
    await _disconnect_mcp(user_id, resolved)
    await _delete_if_user_authored(user_id, resolved)


async def _disconnect_composio(user_id: str, resolved: ResolvedIntegration) -> None:
    """Delete the connected account Composio holds for this provider."""
    composio_service = get_composio_service()
    await composio_service.delete_connected_account(
        user_id=user_id, provider=_require_provider(resolved)
    )


async def _disconnect_self(user_id: str, resolved: ResolvedIntegration) -> None:
    """Revoke the OAuth token GAIA obtained itself."""
    await token_repository.revoke_token(user_id=user_id, provider=_require_provider(resolved))


async def disconnect_integration(user_id: str, integration_id: str) -> IntegrationSuccessResponse:
    """Disconnect an integration for the user."""
    log.set(integration={"provider": integration_id, "action": "disconnect"})
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        raise ValueError(f"Integration {integration_id} not found")

    if resolved.managed_by == "cli":
        # Checked before the custom-source branch: a user-authored CLI
        # integration is `source == "custom"` too, and the MCP teardown would be
        # both wrong and a no-op for it.
        await _disconnect_cli(user_id, resolved)
    elif resolved.source == "custom":
        await _disconnect_custom_mcp(user_id, resolved)
    elif resolved.managed_by == "composio":
        await _disconnect_composio(user_id, resolved)
    elif resolved.managed_by == "self":
        await _disconnect_self(user_id, resolved)
    elif resolved.managed_by == "mcp":
        await _disconnect_mcp(user_id, resolved)
    else:
        raise ValueError(f"Integration {integration_id} disconnect not supported")

    await _invalidate_caches(user_id, integration_id, resolved.managed_by)

    # Reflect the reduced connected set in the user's workspace VFS.
    schedule_user_integrations_sync(user_id)

    log.set(
        integration={
            "provider": integration_id,
            "action": "disconnect",
            "managed_by": resolved.managed_by,
            "status": "disconnected",
        }
    )
    return IntegrationSuccessResponse(
        message=f"Successfully disconnected {resolved.name}",
        integration_id=integration_id,
    )


async def _invalidate_caches(user_id: str, integration_id: str, managed_by: str) -> None:
    """Invalidate relevant caches after disconnect."""
    # Provider metadata cache (24h TTL) is keyed by integration.provider, not
    # integration_id. Without this clear, disconnected integrations keep
    # injecting stale metadata into subagent prompts until the TTL expires.
    integration = get_integration_by_id(integration_id)
    if integration and integration.provider:
        try:
            metadata_key = f"provider_metadata:{user_id}:{integration.provider}"
            await delete_cache(metadata_key)
            log.info(
                f"{LogTag.INTEGRATION} Provider metadata cache invalidated for",
                user_id=user_id,
                provider=integration.provider,
            )
        except redis.RedisError as e:
            log.warning(
                f"{LogTag.INTEGRATION} Failed to invalidate provider metadata cache",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                integration_id=integration_id,
            )

    # Determine whether to delete record or set status to "created"
    if managed_by == "mcp":
        # MCP integrations: record already deleted in main disconnect logic
        log.info(
            f"{LogTag.INTEGRATION} MCP integration record removed", integration_id=integration_id
        )
    else:
        # Check if it's a platform integration (defined in oauth_config.py)
        # If get_integration_by_id returns a value, it's a platform integration
        platform_integration = get_integration_by_id(integration_id)
        if platform_integration:
            # Platform integrations: delete the record entirely
            try:
                await remove_user_integration(user_id, integration_id)
                log.info(
                    f"{LogTag.INTEGRATION} Removed platform integration record",
                    integration_id=integration_id,
                )
            except pymongo.errors.PyMongoError as e:
                log.warning(
                    f"{LogTag.INTEGRATION} Failed to remove integration record",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                    integration_id=integration_id,
                )
        else:
            # Custom integrations: preserve in workspace by setting status to "created"
            try:
                await update_user_integration_status(user_id, integration_id, "created")
                log.info(
                    f"{LogTag.INTEGRATION} Updated status to 'created' for custom integration",
                    integration_id=integration_id,
                )
            except pymongo.errors.PyMongoError as e:
                log.warning(
                    f"{LogTag.INTEGRATION} Failed to update status",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                    integration_id=integration_id,
                )

    # Bust the full per-user integration cache set AFTER the record mutation above,
    # so a cache hiccup can't leave the record stale. Best-effort (never raises).
    await invalidate_user_integration_caches(user_id)
