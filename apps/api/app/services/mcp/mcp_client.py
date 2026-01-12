"""
MCP Client wrapper.

Implements complete MCP OAuth 2.1 authorization flow per specification.
See: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
"""

import base64
import urllib.parse
from typing import Optional

import httpx
from langchain_core.tools import BaseTool
from mcp_use import MCPClient as BaseMCPClient
from mcp_use.agents.adapters.langchain_adapter import LangChainAdapter

from app.config.loggers import langchain_logger as logger

from app.models.oauth_models import MCPConfig
from app.services.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.utils.mcp_oauth_utils import (
    extract_auth_challenge,
    fetch_auth_server_metadata,
    fetch_protected_resource_metadata,
    find_protected_resource_metadata,
)
from app.utils.mcp_utils import (
    generate_pkce_pair,
    wrap_tools_with_null_filter,
)


class DCRNotSupportedException(Exception):
    """Raised when Dynamic Client Registration is not supported by the server."""

    pass


class MCPClient:
    """
    MCP client wrapper implementing MCP OAuth 2.1 spec.

    OAuth flow per MCP specification:
    1. Attempt connection → 401 Unauthorized with WWW-Authenticate header
    2. Parse resource_metadata URL from WWW-Authenticate
    3. Fetch Protected Resource Metadata (RFC 9728)
    4. Discover authorization server and fetch its metadata (RFC 8414)
    5. DCR with authorization server if no client_id (RFC 7591)
    6. Standard OAuth 2.1 authorization code flow with PKCE
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.token_store = MCPTokenStore(user_id)
        self._clients: dict[str, BaseMCPClient] = {}
        self._tools: dict[str, list[BaseTool]] = {}

    async def probe_connection(self, server_url: str) -> dict:
        """
        Probe an MCP server to determine auth requirements.

        Returns:
            {
                "requires_auth": bool,
                "auth_type": "none" | "oauth",
                "oauth_challenge": dict,  # if OAuth, contains WWW-Authenticate data
                "error": str,  # if probe failed
            }
        """
        try:
            challenge = await extract_auth_challenge(server_url)

            if challenge.get("raw"):
                logger.debug(f"OAuth required for {server_url}")
                return {
                    "requires_auth": True,
                    "auth_type": "oauth",
                    "oauth_challenge": challenge,
                }

            logger.debug(f"No auth required for {server_url}")
            return {
                "requires_auth": False,
                "auth_type": "none",
            }

        except Exception as e:
            logger.warning(f"Probe failed for {server_url}: {e}")
            return {
                "requires_auth": False,
                "auth_type": "unknown",
                "error": str(e),
            }

    async def update_integration_auth_status(
        self,
        integration_id: str,
        requires_auth: bool,
        auth_type: str,
    ) -> None:
        """
        Update integration auth status in MongoDB after probe discovery.

        This ensures the stored mcp_config reflects the actual auth requirements
        discovered from the MCP server, fixing stale requires_auth flags.

        Args:
            integration_id: The integration ID to update
            requires_auth: Whether auth is required
            auth_type: The auth type ("oauth", "none", etc.)
        """
        from app.db.mongodb.collections import integrations_collection

        try:
            result = await integrations_collection.update_one(
                {"integration_id": integration_id},
                {
                    "$set": {
                        "mcp_config.requires_auth": requires_auth,
                        "mcp_config.auth_type": auth_type,
                    }
                },
            )
            if result.modified_count > 0:
                logger.info(
                    f"Updated auth status for {integration_id}: "
                    f"requires_auth={requires_auth}, auth_type={auth_type}"
                )
        except Exception as e:
            logger.warning(f"Failed to update auth status for {integration_id}: {e}")

    async def _discover_oauth_config(
        self, integration_id: str, mcp_config: MCPConfig
    ) -> dict:
        """
        Full MCP OAuth discovery flow per specification.

        Returns dict with all OAuth endpoints and metadata.
        """
        cached = await self.token_store.get_oauth_discovery(integration_id)
        if cached:
            logger.debug(f"Using cached OAuth discovery for {integration_id}")
            return cached

        if mcp_config.oauth_metadata:
            logger.debug(f"Using explicit OAuth metadata for {integration_id}")
            return mcp_config.oauth_metadata

        server_url = mcp_config.server_url.rstrip("/")

        # Phase 1: Probe server for WWW-Authenticate challenge
        challenge = await extract_auth_challenge(server_url)
        initial_scope = challenge.get("scope")

        # Phase 2: Try RFC 9728 Protected Resource Metadata discovery
        prm = None
        prm_error = None

        try:
            prm_url = challenge.get("resource_metadata")
            if not prm_url:
                prm_url = await find_protected_resource_metadata(server_url)

            if prm_url:
                prm = await fetch_protected_resource_metadata(prm_url)
                logger.info(f"Fetched PRM for {integration_id} from {prm_url}")

        except Exception as e:
            prm_error = str(e)
            logger.info(f"RFC 9728 PRM discovery failed for {integration_id}: {e}")

        if prm and prm.get("authorization_servers"):
            auth_server_url = prm["authorization_servers"][0]
            logger.info(f"Using auth server from PRM: {auth_server_url}")

            auth_metadata = await fetch_auth_server_metadata(auth_server_url)

            discovery = {
                "resource": prm.get("resource", server_url),
                "scopes_supported": prm.get("scopes_supported", []),
                "initial_scope": initial_scope,
                "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
                "token_endpoint": auth_metadata.get("token_endpoint"),
                "registration_endpoint": auth_metadata.get("registration_endpoint"),
                "issuer": auth_metadata.get("issuer"),
                "discovery_method": "rfc9728_prm",
            }

            await self.token_store.store_oauth_discovery(integration_id, discovery)
            return discovery

        # Phase 3: Fallback - Direct OAuth Discovery on MCP server (RFC 8414)
        logger.info(
            f"Trying direct OAuth discovery for {integration_id} "
            f"(PRM failed: {prm_error or 'no authorization_servers'})"
        )

        try:
            auth_metadata = await fetch_auth_server_metadata(server_url)

            discovery = {
                "resource": server_url,
                "scopes_supported": auth_metadata.get("scopes_supported", []),
                "initial_scope": initial_scope,
                "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
                "token_endpoint": auth_metadata.get("token_endpoint"),
                "registration_endpoint": auth_metadata.get("registration_endpoint"),
                "issuer": auth_metadata.get("issuer"),
                "discovery_method": "direct_oauth",
            }

            await self.token_store.store_oauth_discovery(integration_id, discovery)
            logger.info(f"Direct OAuth discovery succeeded for {integration_id}")
            return discovery

        except Exception as direct_error:
            raise ValueError(
                f"OAuth discovery failed for {integration_id}. "
                f"RFC 9728 PRM: {prm_error or 'no authorization_servers'}. "
                f"Direct OAuth (RFC 8414): {direct_error}"
            )

    async def _build_config(
        self,
        integration_id: str,
        mcp_config: MCPConfig,
    ) -> dict:
        """Build mcp-use config dict."""
        server_config: dict = {"url": mcp_config.server_url}

        if mcp_config.transport:
            server_config["transport"] = mcp_config.transport

        # Check for stored OAuth token if auth is required
        if mcp_config.requires_auth:
            stored_token = await self.token_store.get_oauth_token(integration_id)
            if stored_token:
                # mcp-use HttpConnector handles auth as follows:
                # - If string: adds "Bearer {token}" to Authorization header
                # - So pass raw token WITHOUT Bearer prefix
                raw_token = stored_token
                if stored_token.lower().startswith("bearer "):
                    raw_token = stored_token[7:]  # Remove "Bearer " prefix
                server_config["auth"] = raw_token
            else:
                logger.warning(
                    f"No stored OAuth token found for {integration_id} - connection may fail"
                )

        return {"mcpServers": {integration_id: server_config}}

    async def connect(self, integration_id: str) -> list[BaseTool]:
        """
        Connect to an MCP server and return LangChain tools.

        For unauthenticated MCPs: Connects directly.
        For OAuth MCPs: Uses stored credentials from completed OAuth flow.
        Supports both platform integrations (from code) and custom integrations (from MongoDB).
        """
        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"MCP integration {integration_id} not found")

        mcp_config = resolved.mcp_config
        is_custom = resolved.source == "custom"

        config = await self._build_config(integration_id, mcp_config)

        try:
            client = BaseMCPClient(config)
            await client.create_session(integration_id)

            adapter = LangChainAdapter()
            raw_tools = await adapter.create_tools(client)

            # CRITICAL: Wrap tools to filter None values before MCP invocation.
            # MCP servers expect optional params to be OMITTED, not sent as null.
            # Without this, Pydantic defaults (None) cause MCP validation errors.
            tools = wrap_tools_with_null_filter(raw_tools)

            self._clients[integration_id] = client
            self._tools[integration_id] = tools

            logger.info(f"[{integration_id}] Connected to MCP, got {len(tools)} tools")

            # Build tool metadata for MongoDB (name and description only)
            tool_metadata = [
                {
                    "name": t.name,
                    "description": t.description,
                }
                for t in tools
            ]

            logger.info(
                f"[{integration_id}] Storing {len(tool_metadata)} tools to MongoDB"
            )

            # Store tool names/descriptions globally in MongoDB for frontend visibility
            global_store = get_mcp_tools_store()
            await global_store.store_tools(integration_id, tool_metadata)

            logger.info(f"[{integration_id}] store_tools() completed successfully")

            # For custom integrations: index tools in ChromaDB
            if is_custom:
                await self._handle_custom_integration_connect(
                    integration_id, mcp_config.server_url, tools
                )

            # Update user integration status to connected (import here to avoid circular dependency)
            from app.services.integration_service import update_user_integration_status

            await update_user_integration_status(
                self.user_id, integration_id, "connected"
            )

            return tools

        except Exception as e:
            logger.error(f"Failed to connect to MCP {integration_id}: {e}")
            await self.token_store.update_status(integration_id, "failed", str(e))
            raise

    async def _handle_custom_integration_connect(
        self, integration_id: str, server_url: str, tools: list[BaseTool]
    ) -> None:
        """Index tools in ChromaDB for semantic discovery."""
        try:
            from app.db.chroma.chroma_tools_store import index_tools_to_store

            tools_with_space = [(tool, integration_id) for tool in tools]
            await index_tools_to_store(tools_with_space)
        except Exception as e:
            logger.warning(
                f"Failed to index tools in ChromaDB for {integration_id}: {e}"
            )

    def _resolve_client_credentials(
        self, mcp_config: MCPConfig
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Resolve OAuth client credentials from MCPConfig.

        Supports two patterns:
        1. Direct values: client_id and client_secret set directly
        2. Environment variables: client_id_env and client_secret_env reference settings

        Returns:
            Tuple of (client_id, client_secret), either may be None
        """
        import os

        client_id = mcp_config.client_id
        client_secret = mcp_config.client_secret

        # Resolve from environment variables if direct values not set
        if not client_id and mcp_config.client_id_env:
            client_id = os.getenv(mcp_config.client_id_env)

        if not client_secret and mcp_config.client_secret_env:
            client_secret = os.getenv(mcp_config.client_secret_env)

        return client_id, client_secret

    async def build_oauth_auth_url(
        self,
        integration_id: str,
        redirect_uri: str,
        redirect_path: str = "/integrations",
    ) -> str:
        """
        Build OAuth authorization URL using MCP spec discovery.

        1. Discovers auth server via Protected Resource Metadata
        2. Fetches Authorization Server Metadata for endpoints
        3. Uses DCR on auth server if no client_id configured
        4. Returns authorization URL for browser redirect

        Supports both platform integrations (from code) and custom integrations (from MongoDB).
        """
        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = resolved.mcp_config
        # Full MCP OAuth discovery
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)

        # Get or register client credentials
        client_id, client_secret = self._resolve_client_credentials(mcp_config)

        if not client_id:
            # Try stored DCR client
            dcr_data = await self.token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
            elif oauth_config.get("registration_endpoint"):
                # Perform DCR on the AUTHORIZATION SERVER (not MCP server)
                client_id = await self._register_client(
                    integration_id,
                    oauth_config["registration_endpoint"],
                    redirect_uri,
                )

        if not client_id:
            raise ValueError(
                f"Could not obtain client_id for {integration_id}. "
                "DCR may not be supported - check if pre-registration is required."
            )

        # Generate PKCE pair (required for OAuth 2.1)
        code_verifier, code_challenge = generate_pkce_pair()

        # Create OAuth state (stores code_verifier for token exchange)
        state = await self.token_store.create_oauth_state(integration_id, code_verifier)
        state_data = f"{state}:{integration_id}:{redirect_path}"

        # Build authorization URL
        auth_endpoint = oauth_config.get("authorization_endpoint")
        if not auth_endpoint:
            raise ValueError(
                f"No authorization_endpoint discovered for {integration_id}"
            )

        # Scope selection per MCP spec:
        # 1. Use scope from WWW-Authenticate header (initial_scope) - takes priority
        # 2. Fall back to configured scopes
        # 3. Fall back to scopes_supported from discovery
        scope_str = ""
        if oauth_config.get("initial_scope"):
            # Scope from 401 WWW-Authenticate (priority per spec)
            scope_str = oauth_config["initial_scope"]
        elif mcp_config.oauth_scopes:
            scope_str = " ".join(mcp_config.oauth_scopes)
        elif oauth_config.get("scopes_supported"):
            scope_str = " ".join(oauth_config["scopes_supported"])

        # Get resource URL for token binding (RFC 8707)
        # This ensures the token is bound to the specific MCP server
        resource = oauth_config.get("resource", mcp_config.server_url.rstrip("/"))

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state_data,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": resource,  # CRITICAL: Binds token to MCP server (RFC 8707)
        }
        if scope_str:
            params["scope"] = scope_str

        return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"

    async def _register_client(
        self, integration_id: str, registration_endpoint: str, redirect_uri: str
    ) -> Optional[str]:
        """
        Perform Dynamic Client Registration (RFC 7591) on the authorization server.

        Raises:
            DCRNotSupportedException: If server returns 403/404/405 (DCR not supported)
            ValueError: For other registration failures
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    registration_endpoint,
                    json={
                        "client_name": "GAIA AI Assistant",
                        "redirect_uris": [redirect_uri],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "token_endpoint_auth_method": "none",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                dcr_data = response.json()
                await self.token_store.store_dcr_client(integration_id, dcr_data)
                logger.info(
                    f"DCR successful for {integration_id} at {registration_endpoint}"
                )
                return dcr_data.get("client_id")
        except Exception as e:
            logger.error(
                f"DCR failed for {integration_id} at {registration_endpoint}: {e}"
            )
            raise ValueError(f"Dynamic Client Registration failed: {e}")

    async def handle_oauth_callback(
        self,
        integration_id: str,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> list[BaseTool]:
        """Exchange authorization code for tokens and connect."""
        is_valid, code_verifier = await self.token_store.verify_oauth_state(
            integration_id, state
        )
        if not is_valid:
            raise ValueError("Invalid OAuth state")

        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = resolved.mcp_config

        # Get OAuth config (should be cached from build_oauth_auth_url)
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)
        token_endpoint = oauth_config.get("token_endpoint")

        if not token_endpoint:
            raise ValueError(f"No token_endpoint for {integration_id}")

        # Get client credentials - check DCR first, then resolve from config/env
        client_id = None
        client_secret = None

        dcr_data = await self.token_store.get_dcr_client(integration_id)
        if dcr_data:
            client_id = dcr_data.get("client_id")
            client_secret = dcr_data.get("client_secret")

        if not client_id or not client_secret:
            resolved_id, resolved_secret = self._resolve_client_credentials(mcp_config)
            if not client_id:
                client_id = resolved_id
            if not client_secret:
                client_secret = resolved_secret

        # Get resource for token binding (RFC 8707)
        resource = oauth_config.get("resource", mcp_config.server_url.rstrip("/"))

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "resource": resource,  # CRITICAL: Bind token to MCP server (RFC 8707)
            }

            # Include PKCE code_verifier if we have it (required for OAuth 2.1)
            if code_verifier:
                token_data["code_verifier"] = code_verifier

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            if client_secret:
                credentials = f"{client_id}:{client_secret}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            else:
                token_data["client_id"] = client_id

            response = await client.post(
                token_endpoint, data=token_data, headers=headers, timeout=30
            )

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.status_code}")
                logger.error(f"Response: {response.text}")

            response.raise_for_status()
            tokens = response.json()

        # Store tokens
        await self.token_store.store_oauth_tokens(
            integration_id=integration_id,
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token"),
        )

        try:
            return await self.connect(integration_id)
        except Exception as e:
            logger.warning(
                f"MCP connection after OAuth failed for {integration_id}: {e}"
            )
            return []

    async def disconnect(self, integration_id: str) -> None:
        """Disconnect from an MCP server."""
        resolved = await IntegrationResolver.resolve(integration_id)
        if resolved and resolved.mcp_config and not resolved.requires_auth:
            return

        if integration_id in self._clients:
            try:
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

    async def get_all_connected_tools(self) -> dict[str, list[BaseTool]]:
        """
        Get tools from all connected MCP integrations for this user.

        Always connects to get real tools with proper schemas.
        Cached tools are returned from memory if already connected.

        Returns dict mapping integration_id -> list of tools.
        """
        # Get authenticated MCP connections from PostgreSQL
        auth_connected = await self.token_store.get_connected_integrations()

        # Get unauthenticated MCP connections from MongoDB user_integrations
        unauth_connected: list[str] = []
        try:
            from app.services.integration_service import get_user_connected_integrations

            user_integrations = await get_user_connected_integrations(self.user_id)
            for ui in user_integrations:
                integration_id = ui.get("integration_id")
                # Skip if already in auth_connected (avoid duplicates)
                if integration_id and integration_id not in auth_connected:
                    unauth_connected.append(integration_id)
        except Exception as e:
            logger.warning(f"Failed to get unauth MCPs from user_integrations: {e}")

        # Combine both sources
        connected_ids = list(set(auth_connected) | set(unauth_connected))
        all_tools: dict[str, list[BaseTool]] = {}

        for integration_id in connected_ids:
            try:
                # Check if already connected in memory (live tools with schemas)
                if integration_id in self._tools:
                    all_tools[integration_id] = self._tools[integration_id]
                    continue

                # Connect to get real tools with proper schemas
                # This is required because stubs without args_schema cause LLM
                # to use wrong parameter names (e.g., "name" instead of "query")
                tools = await self.connect(integration_id)
                if tools:
                    all_tools[integration_id] = tools

            except Exception as e:
                logger.warning(f"Failed to get tools for MCP {integration_id}: {e}")

        return all_tools

    async def ensure_connected(self, integration_id: str) -> list[BaseTool]:
        """
        Ensure connection to an MCP server, reconnecting if needed.

        Uses stored tokens to reconnect if not already connected in memory.
        """
        # Already connected in memory
        if integration_id in self._tools:
            return self._tools[integration_id]

        # Check if we have stored credentials
        if await self.token_store.is_connected(integration_id):
            return await self.connect(integration_id)

        # Not connected at all
        raise ValueError(
            f"MCP {integration_id} not connected. User needs to complete OAuth flow."
        )


async def get_mcp_client(user_id: str) -> MCPClient:
    """Get MCP client for a user from the pool."""
    from app.services.mcp.mcp_client_pool import get_mcp_client_pool

    pool = await get_mcp_client_pool()
    return await pool.get(user_id)
