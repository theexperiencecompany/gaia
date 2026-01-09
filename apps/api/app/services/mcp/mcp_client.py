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
from app.db.mongodb.collections import integrations_collection
from app.helpers.mcp_helpers import create_stub_tools_from_cache
from app.models.oauth_models import MCPConfig
from app.services.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.utils.favicon_utils import fetch_favicon_from_url
from app.utils.mcp_oauth_utils import (
    extract_auth_challenge,
    fetch_auth_server_metadata,
    fetch_protected_resource_metadata,
    find_protected_resource_metadata,
)
from app.utils.mcp_utils import (
    generate_pkce_pair,
    serialize_args_schema,
    wrap_tools_with_null_filter,
)


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

        Used to quickly check if an MCP server requires authentication
        before attempting a full connection.

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

            # If we got a 401 with WWW-Authenticate, OAuth is required
            if challenge.get("raw"):
                logger.info(f"Probe {server_url}: OAuth required")
                return {
                    "requires_auth": True,
                    "auth_type": "oauth",
                    "oauth_challenge": challenge,
                }

            # No 401 = no auth required, or server accepts anonymous access
            logger.info(f"Probe {server_url}: No auth required")
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

        # ALWAYS check for stored OAuth token, regardless of requires_auth flag.
        # This handles custom integrations where OAuth was discovered dynamically
        # but requires_auth was never updated in MongoDB from false to true.
        stored_token = await self.token_store.get_oauth_token(integration_id)
        if stored_token:
            # Debug: log token details (safely)
            logger.info(
                f"OAuth token for {integration_id}: "
                f"length={len(stored_token)}, "
                f"starts_with_bearer={stored_token.lower().startswith('bearer ')}, "
                f"preview={stored_token[:20]}..."
            )
            # mcp-use HttpConnector handles auth as follows:
            # - If string: adds "Bearer {token}" to Authorization header
            # - So pass raw token WITHOUT Bearer prefix
            raw_token = stored_token
            if stored_token.lower().startswith("bearer "):
                raw_token = stored_token[7:]  # Remove "Bearer " prefix
            server_config["auth"] = raw_token
        elif mcp_config.requires_auth:
            # Only warn if requires_auth is explicitly set - means token should exist
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

            # Debug: log each tool's schema (DEBUG level to reduce noise)
            logger.debug(f"=== MCP Tools Schema Debug for {integration_id} ===")
            for t in tools:
                # Check tool.args as suggested by mcp-use docs
                tool_args = getattr(t, "args", None)
                logger.debug(f"MCP tool '{t.name}': args={tool_args}")

                if hasattr(t, "args_schema") and t.args_schema:
                    try:
                        schema = t.args_schema.model_json_schema()
                        props = schema.get("properties", {})
                        required = schema.get("required", [])
                        logger.debug(
                            f"  -> {len(props)} properties, required={required}"
                        )

                    except Exception as e:
                        logger.debug(f"MCP tool {t.name}: couldn't get schema: {e}")
                else:
                    logger.debug(f"MCP tool {t.name}: NO args_schema!")

            self._clients[integration_id] = client
            self._tools[integration_id] = tools

            # Build tool metadata with schema for caching
            tool_metadata = [
                {
                    "name": t.name,
                    "description": t.description,
                    "args_schema": serialize_args_schema(t),
                }
                for t in tools
            ]

            # Store in per-user cache (used by stub tools for this user)
            await self.token_store.store_cached_tools(integration_id, tool_metadata)
            logger.info(f"Cached {len(tools)} tools with schema for user")

            # Store tools globally for frontend visibility
            # Always update to ensure latest tools are available (handles tool updates)
            global_store = get_mcp_tools_store()
            await global_store.store_tools(integration_id, tool_metadata)
            logger.info(f"Stored {len(tools)} tools globally for {integration_id}")

            # For custom integrations: fetch favicon and index tools in ChromaDB
            if is_custom:
                await self._handle_custom_integration_connect(
                    integration_id, mcp_config.server_url, tools
                )

            logger.info(f"Connected to MCP {integration_id}: {len(tools)} tools")
            return tools

        except Exception as e:
            logger.error(f"Failed to connect to MCP {integration_id}: {e}")
            await self.token_store.update_status(integration_id, "failed", str(e))
            raise

    async def _handle_custom_integration_connect(
        self, integration_id: str, server_url: str, tools: list[BaseTool]
    ) -> None:
        """
        Handle post-connect tasks for custom integrations.

        1. Fetch and store favicon from the MCP server subdomain
        2. Index tools in ChromaDB for semantic discovery
        """
        # 1. Fetch and store favicon from subdomain
        try:
            icon_url = await fetch_favicon_from_url(server_url)
            if icon_url:
                await integrations_collection.update_one(
                    {"integration_id": integration_id},
                    {"$set": {"icon_url": icon_url}},
                )
                logger.info(f"Stored favicon for {integration_id}: {icon_url}")
        except Exception as e:
            logger.warning(f"Failed to fetch favicon for {integration_id}: {e}")

        # 2. Index tools in ChromaDB for semantic discovery
        try:
            from app.db.chroma.chroma_tools_store import index_tools_to_store

            tools_with_space = [(tool, integration_id) for tool in tools]
            await index_tools_to_store(tools_with_space)
            logger.info(f"Indexed {len(tools)} tools for {integration_id} in ChromaDB")
        except Exception as e:
            logger.warning(
                f"Failed to index tools in ChromaDB for {integration_id}: {e}"
            )

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
        if resolved.source == "custom":
            logger.info(f"Building OAuth URL for custom MCP: {integration_id}")

        # Full MCP OAuth discovery
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)

        # Get or register client credentials
        client_id = mcp_config.client_id

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

        auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(params)}"
        logger.info(
            f"Built OAuth URL for {integration_id}: "
            f"endpoint={auth_endpoint}, resource={resource}, scope={scope_str or '(none)'}"
        )
        return auth_url

    async def _register_client(
        self, integration_id: str, registration_endpoint: str, redirect_uri: str
    ) -> Optional[str]:
        """
        Perform Dynamic Client Registration (RFC 7591) on the authorization server.
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
        if resolved.source == "custom":
            logger.info(f"Handling OAuth callback for custom MCP: {integration_id}")

        # Get OAuth config (should be cached from build_oauth_auth_url)
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)
        token_endpoint = oauth_config.get("token_endpoint")

        if not token_endpoint:
            raise ValueError(f"No token_endpoint for {integration_id}")

        # Get client credentials
        client_id = None
        client_secret = None

        dcr_data = await self.token_store.get_dcr_client(integration_id)
        if dcr_data:
            client_id = dcr_data.get("client_id")
            client_secret = dcr_data.get("client_secret")

        if not client_id:
            client_id = mcp_config.client_id
        if not client_secret:
            client_secret = mcp_config.client_secret

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

        # Debug: Log token info (safely) to understand what we're getting
        access_token = tokens.get("access_token", "")
        logger.info(
            f"Token exchange response for {integration_id}: "
            f"access_token_length={len(access_token)}, "
            f"has_refresh={bool(tokens.get('refresh_token'))}, "
            f"token_type={tokens.get('token_type', 'unknown')}, "
            f"access_token_preview={access_token[:20] if access_token else 'N/A'}..."
        )

        # Store tokens
        await self.token_store.store_oauth_tokens(
            integration_id=integration_id,
            access_token=access_token,
            refresh_token=tokens.get("refresh_token"),
        )

        logger.info(f"OAuth token exchange successful for {integration_id}")

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
            logger.info(f"Skipping disconnect for unauthenticated MCP {integration_id}")
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

        Queries BOTH:
        - mcp_credentials (PostgreSQL) for authenticated MCPs
        - user_integrations (MongoDB) for unauthenticated MCPs user has connected

        For auth-required MCPs: Uses cached tool metadata to create stub tools
        (avoids reconnecting to MCP server just to list tools).
        For unauthenticated MCPs: Connects on-demand.

        Returns dict mapping integration_id -> list of tools.
        """
        # Get authenticated MCP connections from PostgreSQL
        auth_connected = await self.token_store.get_connected_integrations()

        # Get unauthenticated MCP connections from MongoDB user_integrations
        # Import here to avoid circular import
        unauth_connected: list[str] = []
        try:
            from app.services.integration_service import get_user_connected_integrations

            user_integrations = await get_user_connected_integrations(self.user_id)
            for ui in user_integrations:
                integration_id = ui.get("integration_id")
                # Check if this is an unauthenticated MCP via resolver
                resolved = await IntegrationResolver.resolve(integration_id)
                if resolved and resolved.mcp_config and not resolved.requires_auth:
                    unauth_connected.append(integration_id)
        except Exception as e:
            logger.warning(f"Failed to get unauth MCPs from user_integrations: {e}")

        # Combine both sources (deduplicate)
        connected_ids = list(set(auth_connected) | set(unauth_connected))
        all_tools: dict[str, list[BaseTool]] = {}

        for integration_id in connected_ids:
            try:
                # Check if already connected in memory
                if integration_id in self._tools:
                    all_tools[integration_id] = self._tools[integration_id]
                    continue

                resolved = await IntegrationResolver.resolve(integration_id)

                # For auth-required MCPs, try cached tools first
                if resolved and resolved.mcp_config and resolved.requires_auth:
                    cached = await self.token_store.get_cached_tools(integration_id)
                    if cached:
                        stub_tools = create_stub_tools_from_cache(
                            self, integration_id, cached
                        )
                        all_tools[integration_id] = stub_tools
                        logger.info(
                            f"Using {len(stub_tools)} cached tools for {integration_id}"
                        )
                        continue

                # Connect to get real tools
                tools = await self.connect(integration_id)
                if tools:
                    all_tools[integration_id] = tools
                    logger.info(
                        f"Connected to MCP {integration_id}: {len(tools)} tools"
                    )
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
