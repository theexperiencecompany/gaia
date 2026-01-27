"""
OAuth Token Management for MCP integrations.

Handles token refresh, revocation, and client credential resolution.
"""

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from app.config.loggers import langchain_logger as logger
from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_token_store import MCPTokenStore


def resolve_client_credentials(
    mcp_config: MCPConfig,
) -> tuple[Optional[str], Optional[str]]:
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
    refresh_token = await token_store.get_refresh_token(integration_id)
    if not refresh_token:
        return False

    try:
        token_endpoint = oauth_config.get("token_endpoint")
        if not token_endpoint:
            return False

        client_id, client_secret = resolve_client_credentials(mcp_config)
        if not client_id:
            dcr_data = await token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
                client_secret = dcr_data.get("client_secret")

        if not client_id:
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
                return False

            tokens = response.json()

            expires_at = None
            if tokens.get("expires_in"):
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=tokens["expires_in"]
                )

            await token_store.store_oauth_tokens(
                integration_id=integration_id,
                access_token=tokens.get("access_token", ""),
                refresh_token=tokens.get("refresh_token", refresh_token),
                expires_at=expires_at,
            )

            logger.info(f"Successfully refreshed token for {integration_id}")
            return True

    except Exception as e:
        logger.warning(f"Token refresh failed for {integration_id}: {e}")
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

                await http_client.post(
                    revocation_endpoint, data=data, headers=headers, timeout=10
                )
    except Exception as e:
        logger.warning(f"Token revocation failed for {integration_id}: {e}")
