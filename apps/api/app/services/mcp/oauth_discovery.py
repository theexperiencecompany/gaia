"""
OAuth Discovery for MCP integrations.

Handles OAuth 2.1 discovery flow per MCP specification:
- RFC 9728 Protected Resource Metadata discovery
- RFC 8414 Authorization Server Metadata discovery
"""

from app.constants.log_tags import LogTag
from app.constants.mcp import COMPOSIO_MCP_HOST
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.utils.mcp_oauth_utils import (
    OAuthDiscoveryError,
    OAuthSecurityError,
    extract_auth_challenge,
    fetch_auth_server_metadata,
    fetch_protected_resource_metadata,
    find_protected_resource_metadata,
    select_authorization_server,
    validate_https_url,
    validate_oauth_endpoints,
)
from app.utils.url_safety import assert_public_http_url
from mcp.shared.auth import OAuthMetadata
from shared.py.wide_events import log


async def discover_oauth_config(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    challenge_data: dict | None = None,
) -> OAuthDiscovery:
    """Full MCP OAuth discovery flow per specification."""
    cached = await token_store.get_oauth_discovery(integration_id)
    if cached:
        return cached

    if mcp_config.oauth_metadata:
        as_metadata = OAuthMetadata.model_validate(mcp_config.oauth_metadata)
        validate_oauth_endpoints(as_metadata)
        return OAuthDiscovery(
            as_metadata=as_metadata,
            resource=mcp_config.server_url.rstrip("/"),
            discovery_method="preconfigured",
        )

    server_url = mcp_config.server_url.rstrip("/")

    try:
        validate_https_url(server_url)
    except OAuthSecurityError as e:
        log.warning(f"{LogTag.MCP} Server URL security warning for {integration_id}: {e}")

    challenge = challenge_data or await extract_auth_challenge(server_url)
    initial_scope = challenge.get("scope")

    # Try RFC 9728 Protected Resource Metadata
    prm = None
    prm_error = None

    try:
        prm_url = challenge.get("resource_metadata")
        if not prm_url:
            prm_url = await find_protected_resource_metadata(server_url)

        if prm_url:
            prm = await fetch_protected_resource_metadata(prm_url)

    except Exception as e:
        prm_error = str(e)

    if prm and prm.authorization_servers:
        auth_server_url = select_authorization_server(
            [str(s) for s in prm.authorization_servers],
        )

        as_metadata = await fetch_auth_server_metadata(auth_server_url)

        discovery = OAuthDiscovery(
            as_metadata=as_metadata,
            resource=str(prm.resource),
            initial_scope=initial_scope,
            discovery_method="rfc9728_prm",
            prm=prm,
        )

        try:
            validate_oauth_endpoints(as_metadata)
        except OAuthSecurityError as e:
            log.warning(f"{LogTag.MCP} OAuth endpoint security warning: {e}")

        await token_store.store_oauth_discovery(integration_id, discovery)
        return discovery

    # Fallback: Direct OAuth Discovery (RFC 8414)
    try:
        as_metadata = await fetch_auth_server_metadata(server_url)

        discovery = OAuthDiscovery(
            as_metadata=as_metadata,
            resource=server_url,
            initial_scope=initial_scope,
            discovery_method="direct_oauth",
        )

        try:
            validate_oauth_endpoints(as_metadata)
        except OAuthSecurityError as e:
            log.warning(f"{LogTag.MCP} OAuth endpoint security warning: {e}")

        await token_store.store_oauth_discovery(integration_id, discovery)
        return discovery

    except Exception as direct_error:
        raise OAuthDiscoveryError(
            f"OAuth discovery failed for {integration_id}. "
            f"RFC 9728 PRM: {prm_error or 'no authorization_servers'}. "
            f"Direct OAuth (RFC 8414): {direct_error}"
        )


async def probe_mcp_connection(server_url: str) -> dict:
    """Probe an MCP server to determine auth requirements."""
    try:
        # SSRF re-check before the outbound probe (DNS-rebinding defense). A raised
        # ValueError is caught below and surfaced through the existing error dict.
        await assert_public_http_url(server_url)

        challenge = await extract_auth_challenge(server_url)

        # Empty dict => the probe got a non-401 response: no auth required.
        if not challenge:
            return {"requires_auth": False, "auth_type": "none"}

        # Composio's hosted gateways always 401 a probe (no platform x-api-key is
        # sent during probing) but need no *user* auth — the key is injected at
        # connect time. Treat them as no-auth so we don't prompt the user.
        if COMPOSIO_MCP_HOST in server_url:
            return {"requires_auth": False, "auth_type": "none"}

        # A 401 was returned. It's OAuth when the server gives a parseable
        # challenge (WWW-Authenticate header, resource_metadata, or scope);
        # otherwise it's a bare 401 = bearer / API-key auth the user must supply.
        is_oauth = bool(
            challenge.get("raw") or challenge.get("resource_metadata") or challenge.get("scope")
        )
        return {
            "requires_auth": True,
            "auth_type": "oauth" if is_oauth else "bearer",
            "oauth_challenge": challenge,
        }

    except Exception as e:
        return {
            "requires_auth": False,
            "auth_type": "unknown",
            "error": str(e),
        }
