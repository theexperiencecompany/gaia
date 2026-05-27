"""
OAuth Token Management for MCP integrations.

Handles token refresh, revocation, and client credential resolution.
"""

import base64
from datetime import UTC, datetime, timedelta
import os
from urllib.parse import urlparse

import httpx

from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_token_store import MCPTokenStore
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
    oauth_config: dict,
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
        token_endpoint = oauth_config.get("token_endpoint")
        if not token_endpoint:
            log.warning(
                f"try_refresh_token: no token_endpoint in OAuth config for "
                f"{integration_id} user={token_store.user_id}; refresh impossible"
            )
            return False

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

        resource = oauth_config.get("resource", mcp_config.server_url.rstrip("/"))

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

            tokens = response.json()

            access_token = tokens.get("access_token")
            if not access_token:
                log.warning(
                    f"try_refresh_token: 200 OK but no access_token in body for "
                    f"{integration_id} user={token_store.user_id} "
                    f"(keys returned: {list(tokens.keys())})"
                )
                return False

            expires_at = None
            if tokens.get("expires_in"):
                expires_at = datetime.now(UTC) + timedelta(seconds=tokens["expires_in"])

            await token_store.store_oauth_tokens(
                integration_id=integration_id,
                access_token=access_token,
                refresh_token=tokens.get("refresh_token", refresh_token),
                expires_at=expires_at,
            )

            log.info(
                f"try_refresh_token: refreshed token for {integration_id} "
                f"user={token_store.user_id} "
                f"(new_access_token_length={len(access_token)}, "
                f"refresh_token_rotated={('refresh_token' in tokens)}, "
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
    oauth_config: dict,
) -> None:
    """Revoke OAuth tokens per RFC 7009."""
    revocation_endpoint = oauth_config.get("revocation_endpoint")
    if not revocation_endpoint:
        return

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
