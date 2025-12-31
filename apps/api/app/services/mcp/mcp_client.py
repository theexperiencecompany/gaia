"""
MCP Client wrapper for GAIA.

Implements MCP OAuth 2.1 authorization flow per specification:
1. Connect to MCP server → receive 401 with WWW-Authenticate header
2. Fetch Protected Resource Metadata (PRM) from resource_metadata URL
3. Discover authorization server from PRM
4. Fetch Authorization Server Metadata for OAuth endpoints
5. Perform DCR if needed, then OAuth authorization code flow with PKCE
"""

import base64
import hashlib
import re
import secrets
import urllib.parse
from typing import Any, Optional

import httpx
from langchain_core.tools import BaseTool
from mcp_use import MCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter

from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.config.settings import settings
from app.models.oauth_models import MCPConfig
from app.services.mcp.mcp_token_store import MCPTokenStore
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge) tuple.
    """
    # Generate random 32-byte verifier, base64url encode (43-128 chars per spec)
    code_verifier = secrets.token_urlsafe(32)

    # SHA256 hash, then base64url encode (without padding)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    return code_verifier, code_challenge


def _serialize_args_schema(tool: BaseTool) -> dict | None:
    """Serialize tool's args schema to JSON-compatible dict."""
    if not hasattr(tool, "args_schema") or not tool.args_schema:
        logger.debug(f"Tool {tool.name} has no args_schema")
        return None

    try:
        schema = tool.args_schema.model_json_schema()
        result = {
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        logger.debug(
            f"Serialized schema for {tool.name}: {len(result.get('properties', {}))} properties"
        )
        return result
    except Exception as e:
        logger.warning(f"Failed to serialize schema for {tool.name}: {e}")
        return None


class GAIAMCPClient:
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
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[BaseTool]] = {}

    async def _probe_for_auth_challenge(self, server_url: str) -> Optional[str]:
        """
        Probe MCP server to get WWW-Authenticate challenge.

        Returns the resource_metadata URL if auth is required, None otherwise.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(server_url, timeout=10)

                if response.status_code == 401:
                    www_auth = response.headers.get("WWW-Authenticate", "")
                    match = re.search(r'resource_metadata="([^"]+)"', www_auth)
                    if match:
                        return match.group(1)
                    logger.warning(
                        f"401 but no resource_metadata in WWW-Authenticate: {www_auth}"
                    )
                return None
        except Exception as e:
            logger.warning(f"Auth probe failed for {server_url}: {e}")
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
        from urllib.parse import urlparse

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
        Full MCP OAuth discovery flow.

        Returns dict with authorization_endpoint, token_endpoint, registration_endpoint, etc.
        """
        # Check if we have cached discovery data
        cached = await self.token_store.get_oauth_discovery(integration_id)
        if cached:
            return cached

        # If explicit metadata provided, use it
        if mcp_config.oauth_metadata:
            return mcp_config.oauth_metadata

        server_url = mcp_config.server_url.rstrip("/")

        # Step 1: Probe server for auth challenge
        prm_url = await self._probe_for_auth_challenge(server_url)

        if not prm_url:
            # Try well-known location as fallback
            prm_url = f"{server_url}/.well-known/oauth-protected-resource"

        # Step 2: Fetch Protected Resource Metadata
        try:
            prm = await self._fetch_protected_resource_metadata(prm_url)
        except Exception as e:
            logger.error(f"Failed to fetch PRM from {prm_url}: {e}")
            raise ValueError(
                f"Could not discover OAuth config for {integration_id}: {e}"
            )

        # Step 3: Get authorization server
        auth_servers = prm.get("authorization_servers", [])
        if not auth_servers:
            raise ValueError(f"No authorization_servers in PRM for {integration_id}")

        auth_server_url = auth_servers[0]  # Use first one

        # Step 4: Fetch Authorization Server Metadata
        auth_metadata = await self._fetch_auth_server_metadata(auth_server_url)

        # Combine into discovery result
        discovery = {
            "resource": prm.get("resource", server_url),
            "scopes_supported": prm.get("scopes_supported", []),
            "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
            "token_endpoint": auth_metadata.get("token_endpoint"),
            "registration_endpoint": auth_metadata.get("registration_endpoint"),
            "issuer": auth_metadata.get("issuer"),
        }

        # Cache for future use
        await self.token_store.store_oauth_discovery(integration_id, discovery)

        return discovery

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
                # mcp-use accepts auth as string for bearer token
                server_config["auth"] = stored_token
                logger.info(
                    f"Using stored OAuth token for {integration_id} (token: {stored_token[:10]}...)"
                )
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
            client = MCPClient(config)
            await client.create_session(integration_id)

            adapter = LangChainAdapter()
            tools = await adapter.create_tools(client)

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
                        # Log property details for the first tool as sample
                        if t.name == "browserbase_session_create":
                            for prop_name, prop_info in props.items():
                                logger.info(f"  -> prop '{prop_name}': {prop_info}")
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
                    "args_schema": _serialize_args_schema(t),
                }
                for t in tools
            ]

            # Store in per-user cache (used by stub tools for this user)
            await self.token_store.store_cached_tools(integration_id, tool_metadata)
            logger.info(f"Cached {len(tools)} tools with schema for user")

            # Store tools globally for frontend visibility (first connection stores for all users)
            from app.services.mcp.mcp_tools_store import get_mcp_tools_store

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

        # Use discovered scopes or configured ones
        scopes = mcp_config.oauth_scopes or oauth_config.get("scopes_supported", [])
        scope_str = " ".join(scopes) if scopes else ""

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state_data,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scope_str:
            params["scope"] = scope_str

        auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(params)}"
        logger.info(f"Built OAuth URL for {integration_id}: {auth_endpoint}")
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

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
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
        from app.config.oauth_config import get_integration_by_id

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

        def make_stub_executor(client: "GAIAMCPClient", int_id: str, tool_name: str):
            """Factory to create stub executor with proper closure."""

            async def _stub_execute(**kwargs):
                # Connect on-demand and execute the real tool
                tools = await client.ensure_connected(int_id)
                real_tool = next((t for t in tools if t.name == tool_name), None)
                if real_tool:
                    return await real_tool.ainvoke(kwargs)
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
                    # Map JSON schema types to Python types
                    json_type = field_info.get("type", "string")
                    if json_type == "string":
                        field_type = str
                    elif json_type == "integer":
                        field_type = int
                    elif json_type == "number":
                        field_type = float
                    elif json_type == "boolean":
                        field_type = bool
                    elif json_type == "array":
                        field_type = list
                    elif json_type == "object":
                        field_type = dict
                    else:
                        field_type = Any

                    is_required = field_name in required_fields
                    default = ... if is_required else None
                    fields[field_name] = (
                        field_type,
                        Field(
                            default=default,
                            description=field_info.get("description", ""),
                        ),
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


def get_mcp_client(user_id: str) -> GAIAMCPClient:
    """Get MCP client for a user."""
    return GAIAMCPClient(user_id=user_id)
