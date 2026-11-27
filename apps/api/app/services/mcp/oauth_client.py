"""Which OAuth client an MCP integration authorizes, exchanges codes and refreshes tokens as.

Tokens are bound to the client_id they were issued to, so authorization, code
exchange, refresh and revocation all read the client from resolve_oauth_client.
"""

from dataclasses import dataclass
import os

from app.constants.log_tags import LogTag
from app.helpers.mcp_helpers import get_api_base_url
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.utils.mcp_oauth_utils import get_client_metadata_document_url, is_localhost_url
from shared.py.wide_events import log


@dataclass(frozen=True)
class OAuthClient:
    """An OAuth client identity; client_secret is None for a public client."""

    client_id: str
    client_secret: str | None


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


async def resolve_oauth_client(
    token_store: MCPTokenStore,
    integration_id: str,
    mcp_config: MCPConfig,
    oauth_config: OAuthDiscovery,
) -> OAuthClient | None:
    """Return the client from config or env, a stored DCR registration, else the metadata document URL.

    None means no client exists yet: authorization may register one via DCR; a refresh cannot.
    The metadata document URL needs an API base the authorization server can fetch, so not localhost.
    """
    configured_id, configured_secret = resolve_client_credentials(mcp_config)
    if configured_id:
        return OAuthClient(configured_id, configured_secret)

    registration = await token_store.get_dcr_client(integration_id)
    if registration and (registered_id := registration.get("client_id")):
        return OAuthClient(registered_id, registration.get("client_secret"))

    api_base = get_api_base_url()
    if oauth_config.as_metadata.client_id_metadata_document_supported and not is_localhost_url(
        api_base
    ):
        metadata_document_url = get_client_metadata_document_url(api_base)
        log.debug(
            f"{LogTag.MCP} Using client metadata document URL as client_id",
            integration_id=integration_id,
            client_id=metadata_document_url,
        )
        return OAuthClient(metadata_document_url, None)

    return None
