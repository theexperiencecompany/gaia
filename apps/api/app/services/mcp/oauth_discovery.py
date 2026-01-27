"""
OAuth Discovery for MCP integrations.

Handles OAuth 2.1 discovery flow per MCP specification:
- RFC 9728 Protected Resource Metadata discovery
- RFC 8414 Authorization Server Metadata discovery
"""

from typing import Optional

from app.config.loggers import langchain_logger as logger
from app.models.mcp_config import MCPConfig
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


async def discover_oauth_config(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    challenge_data: Optional[dict] = None,
) -> dict:
    """Full MCP OAuth discovery flow per specification."""
    cached = await token_store.get_oauth_discovery(integration_id)
    if cached:
        return cached

    if mcp_config.oauth_metadata:
        validate_oauth_endpoints(mcp_config.oauth_metadata)
        return mcp_config.oauth_metadata

    server_url = mcp_config.server_url.rstrip("/")

    try:
        validate_https_url(server_url)
    except OAuthSecurityError as e:
        logger.warning(f"Server URL security warning for {integration_id}: {e}")

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

    if prm and prm.get("authorization_servers"):
        preferred_server = None
        if mcp_config.oauth_metadata:
            preferred_server = mcp_config.oauth_metadata.get("preferred_auth_server")

        auth_server_url = await select_authorization_server(
            prm["authorization_servers"],
            preferred_server=preferred_server,
        )

        auth_metadata = await fetch_auth_server_metadata(auth_server_url)

        discovery = {
            "resource": prm.get("resource", server_url),
            "scopes_supported": prm.get("scopes_supported", []),
            "initial_scope": initial_scope,
            "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
            "token_endpoint": auth_metadata.get("token_endpoint"),
            "registration_endpoint": auth_metadata.get("registration_endpoint"),
            "revocation_endpoint": auth_metadata.get("revocation_endpoint"),
            "introspection_endpoint": auth_metadata.get("introspection_endpoint"),
            "issuer": auth_metadata.get("issuer"),
            "code_challenge_methods_supported": auth_metadata.get(
                "code_challenge_methods_supported", []
            ),
            "client_id_metadata_document_supported": auth_metadata.get(
                "client_id_metadata_document_supported", False
            ),
            "discovery_method": "rfc9728_prm",
            "authorization_servers": prm.get("authorization_servers", []),
        }

        try:
            validate_oauth_endpoints(discovery)
        except OAuthSecurityError as e:
            logger.warning(f"OAuth endpoint security warning: {e}")

        await token_store.store_oauth_discovery(integration_id, discovery)
        return discovery

    # Fallback: Direct OAuth Discovery (RFC 8414)
    try:
        auth_metadata = await fetch_auth_server_metadata(server_url)

        discovery = {
            "resource": server_url,
            "scopes_supported": auth_metadata.get("scopes_supported", []),
            "initial_scope": initial_scope,
            "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
            "token_endpoint": auth_metadata.get("token_endpoint"),
            "registration_endpoint": auth_metadata.get("registration_endpoint"),
            "revocation_endpoint": auth_metadata.get("revocation_endpoint"),
            "introspection_endpoint": auth_metadata.get("introspection_endpoint"),
            "issuer": auth_metadata.get("issuer"),
            "code_challenge_methods_supported": auth_metadata.get(
                "code_challenge_methods_supported", []
            ),
            "client_id_metadata_document_supported": auth_metadata.get(
                "client_id_metadata_document_supported", False
            ),
            "discovery_method": "direct_oauth",
        }

        try:
            validate_oauth_endpoints(discovery)
        except OAuthSecurityError as e:
            logger.warning(f"OAuth endpoint security warning: {e}")

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
        challenge = await extract_auth_challenge(server_url)

        if challenge.get("raw"):
            return {
                "requires_auth": True,
                "auth_type": "oauth",
                "oauth_challenge": challenge,
            }

        return {"requires_auth": False, "auth_type": "none"}

    except Exception as e:
        return {
            "requires_auth": False,
            "auth_type": "unknown",
            "error": str(e),
        }
