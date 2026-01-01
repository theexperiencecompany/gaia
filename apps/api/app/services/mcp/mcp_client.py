"""
MCP Client wrapper.

Implements complete MCP OAuth 2.1 authorization flow per specification:

Phase 1: Initial Connection Attempt
    - Connect to MCP server → receive 401 with WWW-Authenticate header
    - Parse resource_metadata URL and scope from header

Phase 2: Resource Server Discovery (RFC 9728)
    - Option A: Fetch PRM from resource_metadata URL in header
    - Option B: Try .well-known/oauth-protected-resource URIs
    - Fallback: Direct OAuth discovery on MCP server (RFC 8414)

Phase 3: Authorization Server Discovery (RFC 8414)
    - Fetch .well-known/oauth-authorization-server or openid-configuration

Phase 4: Client Registration
    - Use pre-registered credentials, or
    - Dynamic Client Registration (RFC 7591)

Phase 5: Authorization Flow (OAuth 2.1)
    - PKCE code challenge/verifier (S256)
    - Resource parameter for token binding (RFC 8707)
    - Scope from WWW-Authenticate takes priority

Phase 6: Token Exchange
    - Exchange authorization code for tokens
    - Include resource parameter for token binding

See: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
"""

import base64
import re
import urllib.parse
from typing import Optional
from urllib.parse import urlparse

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from mcp_use import MCPClient as BaseMCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter
from pydantic import Field, create_model

from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.config.settings import settings
from app.models.oauth_models import MCPConfig
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.utils.mcp_utils import (
    extract_type_from_field,
    generate_pkce_pair,
    serialize_args_schema,
    wrap_tools_with_null_filter,
)


class MCPClient:
    """
    GAIA's MCP client wrapper implementing MCP OAuth 2.1 spec.

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

    async def _extract_auth_challenge(self, server_url: str) -> dict:
        """
        Probe MCP server and parse full WWW-Authenticate challenge per MCP spec.

        Per MCP Authorization spec Phase 1:
        - Server returns 401 with WWW-Authenticate header
        - Header may contain: resource_metadata, scope, error, error_description

        Returns dict with extracted fields (empty dict if no 401 or parse fails).
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(server_url, timeout=10)

                if response.status_code == 401:
                    www_auth = response.headers.get("WWW-Authenticate", "")
                    result = {"raw": www_auth}

                    # Extract resource_metadata URL (preferred discovery method)
                    rm_match = re.search(r'resource_metadata="([^"]+)"', www_auth)
                    if rm_match:
                        result["resource_metadata"] = rm_match.group(1)

                    # Extract scope (from initial 401 - takes priority per spec)
                    scope_match = re.search(r'scope="([^"]+)"', www_auth)
                    if scope_match:
                        result["scope"] = scope_match.group(1)

                    # Extract error info (for debugging)
                    error_match = re.search(r'error="([^"]+)"', www_auth)
                    if error_match:
                        result["error"] = error_match.group(1)

                    error_desc_match = re.search(
                        r'error_description="([^"]+)"', www_auth
                    )
                    if error_desc_match:
                        result["error_description"] = error_desc_match.group(1)

                    logger.debug(f"Parsed WWW-Authenticate for {server_url}: {result}")
                    return result

                # Not a 401 - server may not require auth
                return {}

        except Exception as e:
            logger.debug(f"Auth challenge probe failed for {server_url}: {e}")
            return {}

    async def _find_protected_resource_metadata(self, server_url: str) -> Optional[str]:
        """
        Find Protected Resource Metadata via well-known URIs per RFC 9728 Section 5.2.

        Per MCP spec Phase 2b, when no resource_metadata in WWW-Authenticate header,
        try well-known URIs in order:
        1. Path-aware: {origin}/.well-known/oauth-protected-resource{path}
        2. Root: {origin}/.well-known/oauth-protected-resource

        Returns the URL that responds with valid JSON, or None.
        """
        parsed = urlparse(server_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")

        # Build candidates per RFC 9728
        candidates = []
        if path:
            # Path-aware (e.g., /sse → /.well-known/oauth-protected-resource/sse)
            candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
        # Root fallback
        candidates.append(f"{origin}/.well-known/oauth-protected-resource")

        async with httpx.AsyncClient() as client:
            for url in candidates:
                try:
                    response = await client.get(url, timeout=10)
                    if response.status_code == 200:
                        # Verify it's valid JSON with expected fields
                        data = response.json()
                        if "authorization_servers" in data or "resource" in data:
                            logger.info(f"Found Protected Resource Metadata at {url}")
                            return url
                except Exception as e:
                    logger.debug(f"PRM not found at {url}: {e}")

        return None

    async def _fetch_protected_resource_metadata(self, prm_url: str) -> dict:
        """
        Fetch Protected Resource Metadata (RFC 9728).

        Returns dict with 'authorization_servers', 'scopes_supported', etc.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(prm_url, timeout=10)
            response.raise_for_status()
            return response.json()

    async def _fetch_auth_server_metadata(self, auth_server_url: str) -> dict:
        """
        Fetch Authorization Server Metadata (RFC 8414).

        Per RFC 8414, for an issuer URL like https://auth.example.com/tenant1:
        - Path-aware: https://auth.example.com/.well-known/oauth-authorization-server/tenant1
        - Root: https://auth.example.com/.well-known/oauth-authorization-server

        Tries multiple discovery patterns and both OAuth and OIDC endpoints.
        """
        parsed = urlparse(auth_server_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")

        # Build candidate URLs in order of preference
        candidate_urls = []

        # RFC 8414 path-aware discovery (path after .well-known)
        if path:
            candidate_urls.append(
                f"{origin}/.well-known/oauth-authorization-server{path}"
            )
            candidate_urls.append(f"{origin}/.well-known/openid-configuration{path}")

        # Root discovery (most common)
        candidate_urls.append(f"{origin}/.well-known/oauth-authorization-server")
        candidate_urls.append(f"{origin}/.well-known/openid-configuration")

        last_error = None
        async with httpx.AsyncClient() as client:
            for url in candidate_urls:
                try:
                    response = await client.get(url, timeout=10)
                    if response.status_code == 200:
                        logger.debug(f"Found auth server metadata at {url}")
                        return response.json()
                except Exception as e:
                    logger.debug(f"Auth metadata not found at {url}: {e}")
                    last_error = e

        error_msg = f"Failed to fetch auth server metadata for {auth_server_url}"
        logger.error(error_msg)
        raise Exception(error_msg) from last_error

    async def _discover_oauth_config(
        self, integration_id: str, mcp_config: MCPConfig
    ) -> dict:
        """
        Full MCP OAuth discovery flow per specification.

        Implements the complete discovery flow per MCP Authorization spec:
        1. Probe server for WWW-Authenticate challenge (extract resource_metadata, scope)
        2. Try RFC 9728 Protected Resource Metadata discovery
        3. Fallback: Direct OAuth discovery on MCP server (RFC 8414)

        The spec states:
        - MCP servers MUST implement RFC 9728 Protected Resource Metadata
        - MCP clients MUST support both RFC 8414 and OpenID Connect discovery

        Returns dict with all OAuth endpoints and metadata.
        """
        # Check if we have cached discovery data
        cached = await self.token_store.get_oauth_discovery(integration_id)
        if cached:
            logger.debug(f"Using cached OAuth discovery for {integration_id}")
            return cached

        # If explicit metadata provided, use it
        if mcp_config.oauth_metadata:
            logger.debug(f"Using explicit OAuth metadata for {integration_id}")
            return mcp_config.oauth_metadata

        server_url = mcp_config.server_url.rstrip("/")

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 1: Probe server for WWW-Authenticate challenge
        # ═══════════════════════════════════════════════════════════════════
        challenge = await self._extract_auth_challenge(server_url)
        initial_scope = challenge.get(
            "scope"
        )  # Save for auth URL (takes priority per spec)

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 2: Try RFC 9728 Protected Resource Metadata discovery
        # ═══════════════════════════════════════════════════════════════════
        prm = None
        prm_error = None

        try:
            # Option A: resource_metadata from WWW-Authenticate header (preferred)
            prm_url = challenge.get("resource_metadata")

            # Option B: Well-known URI fallback (RFC 9728 Section 5.2)
            if not prm_url:
                prm_url = await self._find_protected_resource_metadata(server_url)

            if prm_url:
                prm = await self._fetch_protected_resource_metadata(prm_url)
                logger.info(f"Fetched PRM for {integration_id} from {prm_url}")

        except Exception as e:
            prm_error = str(e)
            logger.info(f"RFC 9728 PRM discovery failed for {integration_id}: {e}")

        # If we got valid PRM with authorization_servers, use it
        if prm and prm.get("authorization_servers"):
            auth_server_url = prm["authorization_servers"][0]
            logger.info(f"Using auth server from PRM: {auth_server_url}")

            auth_metadata = await self._fetch_auth_server_metadata(auth_server_url)

            discovery = {
                "resource": prm.get("resource", server_url),
                "scopes_supported": prm.get("scopes_supported", []),
                "initial_scope": initial_scope,  # From WWW-Authenticate (priority per spec)
                "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
                "token_endpoint": auth_metadata.get("token_endpoint"),
                "registration_endpoint": auth_metadata.get("registration_endpoint"),
                "issuer": auth_metadata.get("issuer"),
                "discovery_method": "rfc9728_prm",
            }

            await self.token_store.store_oauth_discovery(integration_id, discovery)
            return discovery

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 3: Fallback - Direct OAuth Discovery on MCP server (RFC 8414)
        # ═══════════════════════════════════════════════════════════════════
        # Per MCP spec: "MCP clients MUST support both discovery mechanisms"
        # Some servers (like Linear) expose OAuth metadata directly on the MCP server
        logger.info(
            f"Trying direct OAuth discovery for {integration_id} "
            f"(PRM failed: {prm_error or 'no authorization_servers'})"
        )

        try:
            auth_metadata = await self._fetch_auth_server_metadata(server_url)

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

        # For OAuth integrations, try to use stored token
        if mcp_config.requires_auth:
            stored_token = await self.token_store.get_oauth_token(integration_id)
            if stored_token:
                # Debug: log token details (safely)
                logger.info(
                    f"OAuth token for {integration_id}: "
                    f"length={len(stored_token)}, "
                    f"starts_with_bearer={stored_token.lower().startswith('bearer ')}, "
                    f"preview={stored_token[:20]}..."
                )
                # mcp-use accepts auth as string for bearer token
                server_config["auth"] = stored_token
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
        """
        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"MCP integration {integration_id} not found")

        mcp_config = integration.mcp_config
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

            # Debug: log each tool's schema to see what LLM will see
            logger.info(f"=== MCP Tools Schema Debug for {integration_id} ===")
            for t in tools:
                # Check tool.args as suggested by mcp-use docs
                tool_args = getattr(t, "args", None)
                logger.info(f"MCP tool '{t.name}': args={tool_args}")

                if hasattr(t, "args_schema") and t.args_schema:
                    try:
                        schema = t.args_schema.model_json_schema()
                        props = schema.get("properties", {})
                        required = schema.get("required", [])
                        logger.info(
                            f"  -> {len(props)} properties, required={required}"
                        )

                    except Exception as e:
                        logger.warning(f"MCP tool {t.name}: couldn't get schema: {e}")
                else:
                    logger.warning(f"MCP tool {t.name}: NO args_schema!")

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

            # Store tools globally for frontend visibility (first connection stores for all users)
            global_store = get_mcp_tools_store()
            if not await global_store.has_tools(integration_id):
                await global_store.store_tools(integration_id, tool_metadata)
                logger.info(f"Stored {len(tools)} tools globally for {integration_id}")

            logger.info(f"Connected to MCP {integration_id}: {len(tools)} tools")
            return tools

        except Exception as e:
            logger.error(f"Failed to connect to MCP {integration_id}: {e}")
            await self.token_store.update_status(integration_id, "failed", str(e))
            raise

    def _resolve_secret(
        self, env_name: Optional[str], direct_value: Optional[str]
    ) -> Optional[str]:
        """Resolve secret from Infisical env var or direct value."""
        if env_name:
            value = getattr(settings, env_name, None)
            if value:
                return value
        return direct_value

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
        """
        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = integration.mcp_config

        # Full MCP OAuth discovery
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)

        # Get or register client credentials
        client_id = self._resolve_secret(mcp_config.client_id_env, mcp_config.client_id)

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

        integration = get_integration_by_id(integration_id)
        if not integration or not integration.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = integration.mcp_config

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
            client_id = self._resolve_secret(
                mcp_config.client_id_env, mcp_config.client_id
            )
        if not client_secret:
            client_secret = self._resolve_secret(
                mcp_config.client_secret_env, mcp_config.client_secret
            )

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
            access_token=tokens.get("access_token"),
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
        integration = get_integration_by_id(integration_id)
        if (
            integration
            and integration.mcp_config
            and not integration.mcp_config.requires_auth
        ):
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

        For auth-required MCPs: Uses cached tool metadata to create stub tools
        (avoids reconnecting to MCP server just to list tools).
        For unauthenticated MCPs: Connects on-demand.

        Returns dict mapping integration_id -> list of tools.
        """
        connected_ids = await self.token_store.get_connected_integrations()
        all_tools: dict[str, list[BaseTool]] = {}

        for integration_id in connected_ids:
            try:
                # Check if already connected in memory
                if integration_id in self._tools:
                    all_tools[integration_id] = self._tools[integration_id]
                    continue

                integration = get_integration_by_id(integration_id)

                # For auth-required MCPs, try cached tools first
                if (
                    integration
                    and integration.mcp_config
                    and integration.mcp_config.requires_auth
                ):
                    cached = await self.token_store.get_cached_tools(integration_id)
                    if cached:
                        # Create stub tools from cached metadata
                        stub_tools = self._create_stub_tools_from_cache(
                            integration_id, cached
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
                # Don't mark as failed - might just be a temporary connection issue
                # await self.token_store.update_status(integration_id, "failed", str(e))

        return all_tools

    def _create_stub_tools_from_cache(
        self, integration_id: str, cached_tools: list[dict]
    ) -> list[BaseTool]:
        """
        Create stub BaseTool objects from cached tool metadata.

        These stub tools have the correct name/description for indexing
        but will connect to the MCP server on-demand when actually executed.
        """

        def make_stub_executor(client: "MCPClient", int_id: str, tool_name: str):
            """Factory to create stub executor with proper closure."""

            async def _stub_execute(**kwargs):
                # Filter out null values - MCP servers don't accept nulls,
                # they expect parameters to be omitted if not provided
                filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
                logger.debug(
                    f"Stub {tool_name}: raw args={kwargs}, filtered={filtered_kwargs}"
                )

                # Connect on-demand and execute the real tool
                tools = await client.ensure_connected(int_id)
                real_tool = next((t for t in tools if t.name == tool_name), None)
                if real_tool:
                    return await real_tool.ainvoke(filtered_kwargs)
                raise ValueError(f"Tool {tool_name} not found after connecting")

            return _stub_execute

        stub_tools = []
        for tool_meta in cached_tools:
            name = tool_meta.get("name", "unknown")
            description = tool_meta.get("description", "")

            # Create dynamic model that accepts any kwargs and passes them through
            # The real tool will validate the args after connection
            args_schema = tool_meta.get("args_schema")
            logger.debug(
                f"Stub {name}: args_schema from cache = {args_schema is not None}"
            )
            if (
                args_schema
                and isinstance(args_schema, dict)
                and "properties" in args_schema
            ):
                logger.debug(
                    f"Stub {name}: {len(args_schema.get('properties', {}))} properties, required={args_schema.get('required', [])}"
                )
                # Reconstruct schema from cached JSON schema format
                properties = args_schema.get("properties", {})
                required_fields = args_schema.get("required", [])
                fields = {}
                for field_name, field_info in properties.items():
                    # Extract type from JSON Schema, handling anyOf for nullable types
                    field_type, default_val, is_optional = extract_type_from_field(
                        field_info
                    )

                    is_required = field_name in required_fields

                    # Determine the default value for Pydantic Field:
                    # - Required fields: use ... (no default)
                    # - Optional with schema default: use the schema default
                    # - Optional without default: use None
                    if is_required:
                        field_default = ...
                    elif default_val is not None:
                        field_default = default_val
                    else:
                        field_default = None

                    fields[field_name] = (
                        field_type,
                        Field(
                            default=field_default,
                            description=field_info.get("description", ""),
                        ),
                    )

                    logger.debug(
                        f"Stub {name}.{field_name}: type={field_type.__name__ if hasattr(field_type, '__name__') else field_type}, "
                        f"default={field_default}, required={is_required}"
                    )
                DynamicSchema = create_model(f"{name}Schema", **fields)
            else:
                # Fallback: no schema from cache, let function signature define it
                # This happens if cache was created before schema storage was implemented
                DynamicSchema = None

            stub_tool = StructuredTool.from_function(
                func=lambda **kwargs: None,  # Sync placeholder
                coroutine=make_stub_executor(self, integration_id, name),
                name=name,
                description=description,
                args_schema=DynamicSchema if DynamicSchema else None,
            )
            stub_tools.append(stub_tool)

        return stub_tools

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


def get_mcp_client(user_id: str) -> MCPClient:
    """Get MCP client for a user."""
    return MCPClient(user_id=user_id)
