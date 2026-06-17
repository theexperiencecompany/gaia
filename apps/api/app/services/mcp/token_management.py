"""
OAuth Token Management for MCP integrations.

Handles token refresh, revocation, and client credential resolution.
"""

import base64
from datetime import UTC, datetime, timedelta
import os
from urllib.parse import urlparse

import httpx

from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_token_store import MCPTokenStore
from mcp.shared.auth import OAuthToken
from shared.py.wide_events import log


def _endpoint_host(url: str | None) -> str | None:
    """Return `scheme://host` of an endpoint URL for safe logging."""
    if not url:
        return None
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None


def resolve_client_credentials(
    mcp_config: MCPConfig,
) -> tuple[str | None, str | None]:
    """Resolve OAuth client credentials from config or environment."""
    client_id = mcp_config.client_id
    client_secret = mcp_config.client_secret

    if not client_id and mcp_config.client_id_env:
        client_id = os.getenv(mcp_config.client_id_env)

    if not client_secret and mcp_config.client_secret_env:
        client_secret = os.getenv(mcp_config.client_secret_env)

    return client_id, client_secret


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
            f"try_refresh_token: no refresh_token stored for {integration_id} "
            f"user={token_store.user_id}; user must re-OAuth"
        )
        return False

    try:
        token_endpoint = str(oauth_config.as_metadata.token_endpoint)

        client_id, client_secret = resolve_client_credentials(mcp_config)
        if not client_id:
            dcr_data = await token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
                client_secret = dcr_data.get("client_secret")

        if not client_id:
            log.warning(
                f"try_refresh_token: no client_id resolved for {integration_id} "
                f"user={token_store.user_id} (no pre-configured creds, no DCR "
                f"registration); user must re-authorize"
            )
            return False

        resource = oauth_config.resource

        async with httpx.AsyncClient() as http_client:
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "resource": resource,
            }

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            if client_secret:
                credentials = f"{client_id}:{client_secret}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            else:
                token_data["client_id"] = client_id

            response = await http_client.post(
                token_endpoint, data=token_data, headers=headers, timeout=30
            )

            if response.status_code != 200:
                error_code = None
                error_description = None
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error_code = payload.get("error")
                        error_description = payload.get("error_description")
                except ValueError:
                    pass

                log.warning(
                    f"try_refresh_token: token endpoint returned "
                    f"{response.status_code} for {integration_id} "
                    f"user={token_store.user_id} "
                    f"(oauth_error={error_code!r}, desc={error_description!r}) "
                    f"endpoint={_endpoint_host(token_endpoint)}"
                )
                return False

            token = OAuthToken.model_validate(response.json())

            expires_at = None
            if token.expires_in:
                expires_at = datetime.now(UTC) + timedelta(seconds=token.expires_in)

            await token_store.store_oauth_tokens(
                integration_id=integration_id,
                access_token=token.access_token,
                refresh_token=token.refresh_token or refresh_token,
                expires_at=expires_at,
            )

            log.info(
                f"try_refresh_token: refreshed token for {integration_id} "
                f"user={token_store.user_id} "
                f"(new_access_token_length={len(token.access_token)}, "
                f"refresh_token_rotated={token.refresh_token is not None}, "
                f"expires_at={expires_at})"
            )
            return True

    except Exception as e:
        log.warning(
            f"try_refresh_token: exception during refresh for "
            f"{integration_id} user={token_store.user_id}: "
            f"{type(e).__name__}: {e}"
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

    client_id, client_secret = resolve_client_credentials(mcp_config)
    if not client_id:
        dcr_data = await token_store.get_dcr_client(integration_id)
        if dcr_data:
            client_id = dcr_data.get("client_id")
            client_secret = dcr_data.get("client_secret")

    tokens_to_revoke = []

    refresh_token = await token_store.get_refresh_token(integration_id)
    if refresh_token:
        tokens_to_revoke.append(("refresh_token", refresh_token))

    access_token = await token_store.get_oauth_token(integration_id)
    if access_token:
        tokens_to_revoke.append(("access_token", access_token))

    try:
        async with httpx.AsyncClient() as http_client:
            for token_type, token in tokens_to_revoke:
                data = {"token": token, "token_type_hint": token_type}
                if client_id:
                    data["client_id"] = client_id

                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                if client_secret:
                    credentials = f"{client_id}:{client_secret}"
                    encoded = base64.b64encode(credentials.encode()).decode()
                    headers["Authorization"] = f"Basic {encoded}"

                await http_client.post(revocation_endpoint, data=data, headers=headers, timeout=10)
    except Exception as e:
        log.warning(f"Token revocation failed for {integration_id}: {e}")
