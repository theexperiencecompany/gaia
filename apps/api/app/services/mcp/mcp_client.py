"""
MCP Client wrapper for GAIA using mcp-use library.

Handles connection management, authentication, and LangChain tool conversion.
Follows same patterns as ComposioService for parity.
"""

import urllib.parse
from typing import Optional, TypedDict

import httpx
from langchain_core.tools import BaseTool
from mcp_use import MCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter

from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.config.settings import settings
from app.models.oauth_models import MCPConfig
from app.services.mcp.mcp_token_store import MCPTokenStore


class OAuthMetadata(TypedDict):
    """OAuth server metadata from .well-known discovery."""

    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str


class GAIAMCPClient:
    """
    GAIA's MCP client wrapper.

    Provides connection management, authentication handling, and tool conversion.
    Designed to be indistinguishable from Composio in API patterns.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.token_store = MCPTokenStore(user_id)
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[BaseTool]] = {}

    async def connect(
        self,
        integration_id: str,
        bearer_token: Optional[str] = None,
    ) -> list[BaseTool]:
        """
        Connect to an MCP server and return LangChain tools.

        Args:
            integration_id: The integration ID from oauth_config
            bearer_token: Optional bearer token for bearer auth (new connections)

        Returns:
            List of LangChain BaseTool objects
        """
        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"MCP integration {integration_id} not found")

        mcp_config = integration.mcp_config
        config = await self._build_config(integration_id, mcp_config, bearer_token)

        try:
            client = MCPClient(config)
            await client.create_session(integration_id)

            # Use LangChainAdapter to convert MCP tools
            adapter = LangChainAdapter()
            tools = await adapter.create_tools(client)

            self._clients[integration_id] = client
            self._tools[integration_id] = tools

            # Store connection based on auth type
            if mcp_config.auth_type == "bearer" and bearer_token:
                await self.token_store.store_bearer_token(integration_id, bearer_token)
            # Note: auth_type="none" doesn't need storage - always connected

            logger.info(f"Connected to MCP {integration_id}: {len(tools)} tools")
            return tools

        except Exception as e:
            logger.error(f"Failed to connect to MCP {integration_id}: {e}")
            await self.token_store.update_status(integration_id, "failed", str(e))
            raise

    async def _build_config(
        self,
        integration_id: str,
        mcp_config: MCPConfig,
        bearer_token: Optional[str] = None,
    ) -> dict:
        """Build mcp-use config dict with proper authentication."""
        server_config: dict = {"url": mcp_config.server_url}

        if mcp_config.auth_type == "none":
            pass  # No auth needed

        elif mcp_config.auth_type == "bearer":
            # Get token from param or stored credentials
            token = bearer_token or await self.token_store.get_bearer_token(
                integration_id
            )
            if token:
                server_config["auth"] = token

        elif mcp_config.auth_type == "oauth":
            # Get stored OAuth token
            stored_token = await self.token_store.get_oauth_token(integration_id)
            logger.info(
                f"OAuth token for {integration_id}: {'found' if stored_token else 'NOT FOUND'}"
            )

            if stored_token:
                # We have a token - pass it as bearer auth
                server_config["auth"] = stored_token
                server_config["headers"] = {"Authorization": f"Bearer {stored_token}"}
                logger.info(f"Set OAuth token as bearer auth for {integration_id}")
            elif mcp_config.use_dcr:
                # No token yet, but we have DCR - pass client credentials to mcp-use
                dcr_data = await self.token_store.get_dcr_client(integration_id)
                if dcr_data:
                    # Pass DCR credentials so mcp-use can complete OAuth
                    server_config["auth"] = {
                        "client_id": dcr_data.get("client_id"),
                        "client_secret": dcr_data.get("client_secret"),
                    }
                    logger.info(f"Set DCR credentials for {integration_id}")
            # Note: If no stored token and no DCR, OAuth flow must be triggered
            # via build_oauth_auth_url() and handle_oauth_callback()

        return {"mcpServers": {integration_id: server_config}}

    def _resolve_secret(
        self, env_name: Optional[str], direct_value: Optional[str]
    ) -> Optional[str]:
        """Resolve secret from Infisical env var or direct value."""
        if env_name:
            value = getattr(settings, env_name, None)
            if value:  # Only return if value is truthy
                return value
        return direct_value

    def _get_oauth_base_url(self, mcp_config: MCPConfig) -> str:
        """
        Get OAuth base URL from config.

        Note: oauth_base_url is required when auth_type is 'oauth' (enforced by MCPConfig validator).
        """
        if not mcp_config.oauth_base_url:
            raise ValueError(
                "oauth_base_url is required for OAuth MCP integrations. "
                "This should be enforced by MCPConfig validation."
            )
        return mcp_config.oauth_base_url.rstrip("/")

    async def _discover_oauth_metadata(self, base_url: str) -> OAuthMetadata:
        """Discover OAuth endpoints from .well-known endpoint."""
        try:
            discovery_url = f"{base_url}/.well-known/oauth-authorization-server"
            async with httpx.AsyncClient() as client:
                response = await client.get(discovery_url, timeout=10)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"OAuth discovery failed for {base_url}: {e}")
            return {
                "authorization_endpoint": f"{base_url}/authorize",
                "token_endpoint": f"{base_url}/token",
                "registration_endpoint": f"{base_url}/register",
            }

    async def build_oauth_auth_url(
        self,
        integration_id: str,
        redirect_uri: str,
        redirect_path: str = "/integrations",
    ) -> str:
        """
        Build OAuth authorization URL for the MCP server.

        Discovers OAuth metadata and handles DCR if needed.
        """
        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = integration.mcp_config

        # Get OAuth base URL and discover metadata
        base_url = self._get_oauth_base_url(mcp_config)

        # Use explicit endpoints if provided, otherwise discover
        if mcp_config.oauth_authorize_endpoint and mcp_config.oauth_token_endpoint:
            logger.info(f"Using explicit OAuth endpoints for {integration_id}")
            oauth_metadata = {
                "authorization_endpoint": mcp_config.oauth_authorize_endpoint,
                "token_endpoint": mcp_config.oauth_token_endpoint,
                # For DCR, derive registration endpoint from oauth_base_url
                "registration_endpoint": f"{base_url}/register"
                if mcp_config.use_dcr
                else None,
            }
        else:
            oauth_metadata = await self._discover_oauth_metadata(base_url)

        async with httpx.AsyncClient() as http_client:
            # Get client_id - either from config or DCR
            logger.info(
                f"Resolving client_id for {integration_id}: env={mcp_config.client_id_env}, direct={mcp_config.client_id}"
            )
            client_id = self._resolve_secret(
                mcp_config.client_id_env, mcp_config.client_id
            )
            logger.info(
                f"Resolved client_id for {integration_id}: {client_id is not None}"
            )

            # If use_dcr is True and no client_id, try Dynamic Client Registration
            if not client_id and mcp_config.use_dcr:
                # Check if we have a stored DCR registration
                stored_client = await self.token_store.get_dcr_client(integration_id)
                if stored_client:
                    client_id = stored_client.get("client_id")
                else:
                    # Register dynamically
                    registration_endpoint = oauth_metadata.get("registration_endpoint")
                    if registration_endpoint:
                        try:
                            reg_response = await http_client.post(
                                registration_endpoint,
                                json={
                                    "client_name": "GAIA AI Assistant",
                                    "redirect_uris": [redirect_uri],
                                    "grant_types": [
                                        "authorization_code",
                                        "refresh_token",
                                    ],
                                    "response_types": ["code"],
                                    "token_endpoint_auth_method": "none",  # Public client
                                },
                                timeout=30,
                            )
                            reg_response.raise_for_status()
                            dcr_data = reg_response.json()
                            client_id = dcr_data.get("client_id")

                            # Store DCR registration
                            await self.token_store.store_dcr_client(
                                integration_id, dcr_data
                            )
                            logger.info(f"DCR successful for {integration_id}")
                        except Exception as e:
                            logger.error(f"DCR failed for {integration_id}: {e}")
                            raise ValueError(f"Dynamic Client Registration failed: {e}")

            if not client_id:
                raise ValueError(f"No client_id configured for {integration_id}")

        # Create state with user context
        state = await self.token_store.create_oauth_state(integration_id)
        state_data = f"{state}:{integration_id}:{redirect_path}"

        # Build authorization URL
        auth_endpoint = oauth_metadata.get("authorization_endpoint")
        scopes = " ".join(mcp_config.oauth_scopes) if mcp_config.oauth_scopes else ""

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state_data,
        }
        if scopes:
            params["scope"] = scopes

        auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(params)}"
        logger.info(f"Built OAuth URL for {integration_id}")
        return auth_url

    async def handle_oauth_callback(
        self,
        integration_id: str,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> list[BaseTool]:
        """Handle OAuth callback - exchange code for tokens and connect."""
        if not await self.token_store.verify_oauth_state(integration_id, state):
            raise ValueError("Invalid OAuth state")

        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = integration.mcp_config

        # Get OAuth base URL and token endpoint
        base_url = self._get_oauth_base_url(mcp_config)

        # Use explicit token endpoint if provided, otherwise discover
        if mcp_config.oauth_token_endpoint:
            token_endpoint = mcp_config.oauth_token_endpoint
            logger.info(
                f"Using explicit token endpoint for {integration_id}: {token_endpoint}"
            )
        else:
            oauth_metadata = await self._discover_oauth_metadata(base_url)
            token_endpoint = oauth_metadata.get("token_endpoint", f"{base_url}/token")

        async with httpx.AsyncClient() as client:
            # Get client credentials - either from DCR storage, env vars, or config
            client_id = None
            client_secret = None

            if mcp_config.use_dcr:
                # Get DCR-stored credentials
                dcr_data = await self.token_store.get_dcr_client(integration_id)
                if dcr_data:
                    client_id = dcr_data.get("client_id")
                    client_secret = dcr_data.get("client_secret")
                    logger.info(f"Using DCR credentials for {integration_id}")

            # Fallback to env vars or config if no DCR
            if not client_id:
                client_id = self._resolve_secret(
                    mcp_config.client_id_env, mcp_config.client_id
                )
            if not client_secret:
                client_secret = self._resolve_secret(
                    mcp_config.client_secret_env, mcp_config.client_secret
                )

            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }

            # Use Basic Auth if we have secret, otherwise send client_id in body
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            if client_secret:
                # Use HTTP Basic Authentication
                import base64

                credentials = f"{client_id}:{client_secret}"
                encoded_credentials = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded_credentials}"
            else:
                # Public client - send client_id in body
                token_data["client_id"] = client_id

            logger.info(f"Exchanging OAuth code for {integration_id}")

            token_response = await client.post(
                token_endpoint,
                data=token_data,
                headers=headers,
                timeout=30,
            )

            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.status_code}")
                logger.error(f"Response: {token_response.text}")

            token_response.raise_for_status()
            tokens = token_response.json()

            # Log the token response structure (without exposing secrets)
            logger.info(
                f"Token response keys for {integration_id}: {list(tokens.keys())}"
            )
            if "access_token" in tokens:
                logger.info(
                    f"Access token length: {len(tokens.get('access_token', ''))}"
                )
            if "token_type" in tokens:
                logger.info(f"Token type: {tokens.get('token_type')}")

        # Store tokens
        await self.token_store.store_oauth_tokens(
            integration_id=integration_id,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
        )

        logger.info(f"OAuth token exchange successful for {integration_id}")

        # Try to connect to MCP server with the stored tokens
        # If this fails, log the error but OAuth was still successful
        try:
            return await self.connect(integration_id)
        except Exception as e:
            logger.warning(
                f"MCP connection after OAuth failed for {integration_id}: {e}"
            )
            logger.info(
                "OAuth tokens stored successfully, connection will retry on next use"
            )
            return []  # Return empty tools - will be populated on next connect attempt

    async def disconnect(self, integration_id: str) -> None:
        """Disconnect from an MCP server."""
        # Check if this is an unauthenticated MCP - they can't be disconnected
        integration = get_integration_by_id(integration_id)
        if (
            integration
            and integration.mcp_config
            and integration.mcp_config.auth_type == "none"
        ):
            logger.info(f"Skipping disconnect for unauthenticated MCP {integration_id}")
            return

        if integration_id in self._clients:
            try:
                # Close all sessions for this client
                await self._clients[integration_id].close_all_sessions()
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")
            del self._clients[integration_id]

        if integration_id in self._tools:
            del self._tools[integration_id]

        await self.token_store.delete_credentials(integration_id)
        logger.info(f"Disconnected MCP {integration_id}")

    async def get_tools(self, integration_id: str) -> list[BaseTool]:
        """Get tools for a connected integration."""
        return self._tools.get(integration_id, [])

    def is_connected(self, integration_id: str) -> bool:
        """Check if an integration is connected (in memory)."""
        return integration_id in self._clients

    async def is_connected_db(self, integration_id: str) -> bool:
        """Check if an integration is connected (in database)."""
        return await self.token_store.is_connected(integration_id)


def get_mcp_client(user_id: str) -> GAIAMCPClient:
    """
    Get MCP client for a user.

    Creates a new instance per user since each user has separate credentials.
    In-memory caching is intentionally not used here as the client holds
    user-specific state that shouldn't persist between requests.
    """
    return GAIAMCPClient(user_id=user_id)
