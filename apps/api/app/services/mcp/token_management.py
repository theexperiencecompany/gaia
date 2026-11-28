"""
OAuth Token Management for MCP integrations.

Handles token refresh and revocation.
"""

from urllib.parse import urlparse

from app.constants.log_tags import LogTag
from app.models.mcp_config import (
    MCPConfig,
    OAuthDiscovery,
    OAuthErrorResponse,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.oauth_client import resolve_client_credentials, resolve_oauth_client
from app.utils.mcp_oauth_utils import (
    basic_auth_header,
    mcp_http_client,
    oauth_token_expiry,
    parse_oauth_error_response,
)
from mcp.shared.auth import OAuthToken
from shared.py.wide_events import log


def _endpoint_host(url: str | None) -> str | None:
    """Return scheme://host of an endpoint URL for safe logging."""
    if not url:
        return None
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None


async def try_refresh_token(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
) -> bool:
    """Attempt to refresh OAuth token using stored refresh_token."""
    log.set(
        token_refresh={
            "integration_id": integration_id,
            "user_id": token_store.user_id,
            "phase": "start",
        }
    )

    refresh_token = await token_store.get_refresh_token(integration_id)
    if not refresh_token:
        log.warning(
            f"{LogTag.MCP} try_refresh_token: no refresh_token stored for user=; user must re-OAuth",
            integration_id=integration_id,
            user_id=token_store.user_id,
        )
        return False

    try:
        token_endpoint = str(oauth_config.as_metadata.token_endpoint)

        configured_client_id, _ = resolve_client_credentials(mcp_config)
        client = await resolve_oauth_client(token_store, integration_id, mcp_config, oauth_config)
        if client is None:
            # A config gap (an unset client_id_env, a localhost HOST) can cause this, so
            # the grant is kept for when it is fixed; the operator has to see it.
            log.error(
                f"{LogTag.MCP} try_refresh_token: no OAuth client resolves for this integration",
                integration_id=integration_id,
                user_id=token_store.user_id,
            )
            return False
        client_id, client_secret = client.client_id, client.client_secret

        resource = oauth_config.resource

        async with mcp_http_client() as http_client:
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "resource": resource,
            }

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            if client_secret:
                headers["Authorization"] = basic_auth_header(client_id, client_secret)
            else:
                token_data["client_id"] = client_id

            response = await http_client.post(
                token_endpoint, data=token_data, headers=headers, timeout=30
            )

            if response.status_code != 200:
                error_info: OAuthErrorResponse = parse_oauth_error_response(response)
                log.warning(
                    f"{LogTag.MCP} try_refresh_token: token endpoint returned an error",
                    status_code=response.status_code,
                    integration_id=integration_id,
                    user_id=token_store.user_id,
                    oauth_error=error_info["error"],
                    oauth_error_description=error_info["error_description"],
                    endpoint_host=_endpoint_host(token_endpoint),
                )
                if error_info["error"] == "invalid_grant":
                    # The grant itself is dead (revoked/rotated server-side):
                    # no later retry can succeed, so drop it now rather
                    # than letting liveness checks keep reporting recoverable.
                    await token_store.forget_rejected_grant(integration_id, refresh_token)
                elif error_info["error"] == "invalid_client" and not configured_client_id:
                    # The server forgot our registered client (Dodo does): every
                    # authorize URL built from it fails, so drop it and the
                    # grant bound to it; the next connect re-registers.
                    await token_store.forget_rejected_grant(
                        integration_id, refresh_token, client_id=client_id
                    )
                return False

            token = OAuthToken.model_validate(response.json())

            # A 200 with an empty access_token is not a usable refresh — treat it
            # as a failure rather than storing a blank credential.
            if not token.access_token:
                log.warning(
                    f"{LogTag.MCP} try_refresh_token: token endpoint returned an empty access_token for user",
                    integration_id=integration_id,
                    user_id=token_store.user_id,
                )
                return False

            expires_at = oauth_token_expiry(token.expires_in)

            await token_store.store_oauth_tokens(
                integration_id=integration_id,
                access_token=token.access_token,
                refresh_token=token.refresh_token or refresh_token,
                expires_at=expires_at,
            )

            log.info(
                f"{LogTag.MCP} try_refresh_token: refreshed token",
                integration_id=integration_id,
                user_id=token_store.user_id,
                new_access_token_length=len(token.access_token),
                refresh_token_rotated=token.refresh_token is not None,
                expires_at=expires_at,
            )
            return True

    except Exception as e:
        log.warning(
            f"{LogTag.MCP} try_refresh_token: exception during refresh",
            integration_id=integration_id,
            user_id=token_store.user_id,
            error_type=type(e).__name__,
        )
        return False


async def revoke_tokens(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
) -> None:
    """Revoke OAuth tokens per RFC 7009."""
    if not oauth_config.as_metadata.revocation_endpoint:
        return
    revocation_endpoint = str(oauth_config.as_metadata.revocation_endpoint)

    client = await resolve_oauth_client(token_store, integration_id, mcp_config, oauth_config)

    tokens_to_revoke: list[tuple[str, str]] = []

    refresh_token = await token_store.get_refresh_token(integration_id)
    if refresh_token:
        tokens_to_revoke.append(("refresh_token", refresh_token))

    access_token = await token_store.get_oauth_token(integration_id)
    if access_token:
        tokens_to_revoke.append(("access_token", access_token))

    try:
        async with mcp_http_client() as http_client:
            for token_type, token in tokens_to_revoke:
                data = {"token": token, "token_type_hint": token_type}
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                if client:
                    data["client_id"] = client.client_id
                    if client.client_secret:
                        headers["Authorization"] = basic_auth_header(
                            client.client_id, client.client_secret
                        )

                await http_client.post(revocation_endpoint, data=data, headers=headers, timeout=10)
    except Exception as e:
        log.warning(
            f"{LogTag.MCP} Token revocation failed for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def revoke_integration_tokens(token_store: MCPTokenStore, integration_id: str) -> None:
    """Revoke OAuth tokens at authorization server per RFC 7009."""
    try:
        oauth_config = await token_store.get_oauth_discovery(integration_id)
        if not oauth_config:
            return

        resolved = await IntegrationResolver.resolve(integration_id)
        mcp_config = resolved.mcp_config if resolved else None
        if mcp_config:
            await revoke_tokens(token_store, integration_id, mcp_config, oauth_config)
    except Exception as e:
        log.warning(
            f"{LogTag.MCP} Token revocation failed for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
