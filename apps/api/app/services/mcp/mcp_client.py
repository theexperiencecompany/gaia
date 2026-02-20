"""
MCP Client wrapper.

Implements complete MCP OAuth 2.1 authorization flow per specification.
See: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Features:
- RFC 9728 Protected Resource Metadata discovery
- RFC 8414 Authorization Server Metadata discovery
- RFC 7591 Dynamic Client Registration (DCR)
- RFC 8707 Resource Indicators for token binding
- RFC 7009 Token Revocation on disconnect
- RFC 7662 Token Introspection (optional)
- PKCE with S256 (required by MCP)
- Client Metadata Document support (draft-ietf-oauth-client-id-metadata-document)
- OIDC nonce support for OpenID Connect flows
- JWT issuer validation
- HTTPS enforcement for all OAuth endpoints
"""

import asyncio
import base64
import json as _json
import re
import secrets
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from app.config.loggers import langchain_logger as logger
from app.constants.cache import MCP_TOOLS_CACHE_KEY, OAUTH_DISCOVERY_PREFIX
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import index_tools_to_store
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.mcp_config import MCPConfig
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.user_integrations import (
    get_user_connected_integrations,
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.mcp.mcp_client_pool import get_mcp_client_pool
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.services.mcp.oauth_discovery import (
    discover_oauth_config,
    probe_mcp_connection,
)
from app.services.mcp.token_management import (
    resolve_client_credentials,
    revoke_tokens,
    try_refresh_token,
)
from app.utils.mcp_oauth_utils import (
    MCP_PROTOCOL_VERSION,
    OAuthSecurityError,
    get_client_metadata_document_url,
    is_localhost_url,
    parse_oauth_error_response,
    validate_https_url,
    validate_jwt_issuer,
    validate_pkce_support,
    validate_token_response,
)
from app.utils.mcp_utils import (
    generate_pkce_pair,
    wrap_tools_with_null_filter,
)
from langchain_core.tools import BaseTool
from mcp_use import MCPClient as BaseMCPClient
from app.services.mcp.resilient_adapter import ResilientLangChainAdapter


class DCRNotSupportedException(Exception):
    """Raised when Dynamic Client Registration is not supported by the server."""

    pass


class StepUpAuthRequired(Exception):
    """Raised when additional scopes are required (403 insufficient_scope).

    Per MCP spec, this triggers re-authorization with additional scopes.
    """

    def __init__(self, integration_id: str, required_scopes: list[str]):
        self.integration_id = integration_id
        self.required_scopes = required_scopes
        super().__init__(
            f"Step-up authorization required for {integration_id}: {required_scopes}"
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
        self._connecting: dict[str, asyncio.Event] = {}
        self._connect_results: dict[str, list[BaseTool] | None] = {}

    def _sanitize_config(self, config: dict) -> dict:
        """Sanitize config for logging by removing sensitive data."""
        sanitized = {}
        for server_id, server_config in config.get("mcpServers", {}).items():
            sanitized_server = {
                "url": server_config.get("url"),
                "transport": server_config.get("transport"),
                "has_auth": "auth" in server_config
                and server_config["auth"] is not None,
                "has_headers": "headers" in server_config,
            }
            sanitized[server_id] = sanitized_server
        return {"mcpServers": sanitized}

    async def probe_connection(self, server_url: str) -> dict:
        """Probe an MCP server to determine auth requirements."""
        return await probe_mcp_connection(server_url)

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
        self,
        integration_id: str,
        mcp_config: MCPConfig,
        challenge_data: Optional[dict] = None,
    ) -> dict:
        """Full MCP OAuth discovery flow per specification."""
        return await discover_oauth_config(
            self.token_store, integration_id, mcp_config, challenge_data
        )

    async def _build_config(
        self,
        integration_id: str,
        mcp_config: MCPConfig,
    ) -> dict:
        """Build mcp-use config dict.

        Transport selection:
        - If mcp_config.transport is set, use that explicitly
        - Otherwise, defaults to "streamable-http" per MCP spec 2025-11-25
        - SSE transport is deprecated per MCP spec 2025-11-25

        Auth handling:
        - When auth is a string token, mcp-use uses BearerAuth directly
          without OAuth discovery. This is the proper way to pass
          already-obtained tokens to mcp-use.
        """
        server_config: dict = {"url": mcp_config.server_url}

        # Transport: explicit config or let mcp_use auto-detect
        # Per MCP spec 2025-11-25, streamable HTTP is preferred over deprecated SSE
        if mcp_config.transport:
            server_config["transport"] = mcp_config.transport
        else:
            server_config["transport"] = "streamable-http"

        # Check for stored tokens: bearer first (user-provided), then OAuth
        # Bearer tokens can be stored even when requires_auth=False
        stored_token = await self.token_store.get_bearer_token(integration_id)
        token_source = "bearer"  # nosec B105

        # If no bearer token, try OAuth token (only if auth is required)
        if not stored_token and mcp_config.requires_auth:
            # Check if OAuth token is expiring soon and try to refresh
            if await self.token_store.is_token_expiring_soon(integration_id):
                logger.info(
                    f"Token expiring soon for {integration_id}, attempting refresh"
                )
                await self._try_refresh_token(integration_id, mcp_config)

            stored_token = await self.token_store.get_oauth_token(integration_id)
            token_source = "oauth"  # nosec B105

        if stored_token:
            logger.info(
                f"[{integration_id}] Retrieved stored {token_source} token (length={len(stored_token)})"
            )
            # Strip Bearer prefix if present - mcp-use adds it automatically
            raw_token = stored_token
            if stored_token.lower().startswith("bearer "):
                raw_token = stored_token[7:]

            # Primary: Pass token via auth config
            server_config["auth"] = raw_token

            # Fallback: Also pass via headers for servers where mcp-use OAuth
            # discovery fails (e.g., Smithery servers that don't expose
            # .well-known/oauth-authorization-server endpoints)
            server_config["headers"] = {"Authorization": f"Bearer {raw_token}"}
        elif mcp_config.requires_auth:
            logger.warning(
                f"No valid token for {integration_id} - connection may fail. "
                "Token store returned None (check status='connected' requirement)"
            )
        else:
            # No auth required and no bearer token - set auth to None
            server_config["auth"] = None

        return {"mcpServers": {integration_id: server_config}}

    async def connect(self, integration_id: str) -> list[BaseTool]:
        """
        Connect to an MCP server and return LangChain tools.

        For unauthenticated MCPs: Connects directly.
        For OAuth MCPs: Uses stored credentials from completed OAuth flow.
        Supports platform integrations (from code) and custom integrations.

        Deduplicates concurrent connections to the same integration.
        """
        # Return cached tools if already connected
        if integration_id in self._tools:
            return self._tools[integration_id]

        # If another coroutine is already connecting this integration, wait for it
        if integration_id in self._connecting:
            logger.info(f"[{integration_id}] Waiting for concurrent connect to finish")
            await self._connecting[integration_id].wait()
            if integration_id in self._tools:
                return self._tools[integration_id]
            raise ValueError(f"Concurrent connect for {integration_id} failed")

        # Mark as connecting to prevent duplicate work
        self._connecting[integration_id] = asyncio.Event()
        try:
            tools = await self._do_connect(integration_id)
            return tools
        finally:
            event = self._connecting.pop(integration_id, None)
            if event:
                event.set()

    async def _do_connect(self, integration_id: str) -> list[BaseTool]:
        """Internal connect implementation."""
        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"MCP integration {integration_id} not found")

        mcp_config = resolved.mcp_config
        is_custom = resolved.source == "custom"

        config = await self._build_config(integration_id, mcp_config)

        try:
            logger.info(
                f"[{integration_id}] Starting connection to MCP server. Config: {self._sanitize_config(config)}"
            )

            logger.info(f"[{integration_id}] Creating BaseMCPClient instance")
            client = BaseMCPClient(config)

            logger.info(
                f"[{integration_id}] Creating session with integration_id={integration_id}"
            )
            await client.create_session(integration_id)
            logger.info(f"[{integration_id}] Session created successfully")

            # Use resilient adapter that handles invalid schemas gracefully
            # It will skip tools with bad schemas and return the ones that work
            adapter = ResilientLangChainAdapter()
            logger.info(f"[{integration_id}] Converting MCP tools to LangChain format")
            try:
                raw_tools = await adapter.create_tools(client)
            except Exception:
                # Session was created but tool conversion failed — close to avoid leak
                try:
                    await client.close_all_sessions()
                except Exception as close_err:
                    logger.warning(
                        f"[{integration_id}] Failed to close leaked session: {close_err}"
                    )
                raise
            logger.info(
                f"[{integration_id}] Successfully converted {len(raw_tools)} tools to LangChain format"
            )

            # CRITICAL: Wrap tools to filter None values before MCP invocation.
            # MCP servers expect optional params to be OMITTED, not sent as null.
            # Without this, Pydantic defaults (None) cause MCP validation errors.

            # Build a callback to evict stale sessions on connection errors.
            # Pops from dicts AND schedules async session close via fire-and-forget task.
            def _make_evict_callback(iid: str):
                def _evict():
                    stale_client = self._clients.pop(iid, None)
                    self._tools.pop(iid, None)
                    if stale_client:
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(self._safe_close_client(stale_client))
                        except RuntimeError:
                            pass  # No running loop — skip async cleanup
                    logger.info(f"[{iid}] Evicted stale session after connection error")

                return _evict

            tools = wrap_tools_with_null_filter(
                raw_tools, on_connection_error=_make_evict_callback(integration_id)
            )

            self._clients[integration_id] = client
            self._tools[integration_id] = tools

            logger.info(f"[{integration_id}] Connected to MCP, got {len(tools)} tools")

            # Run post-connection DB operations in parallel (all independent)
            post_tasks: list[Any] = []

            # 1. Store unauthenticated record if needed
            if not mcp_config.requires_auth:
                post_tasks.append(
                    self.token_store.store_unauthenticated(integration_id)
                )

            # 2. Store tool metadata to MongoDB for frontend visibility
            tool_metadata = [
                {"name": t.name, "description": t.description} for t in tools
            ]
            logger.info(
                f"[{integration_id}] Storing {len(tool_metadata)} tools to MongoDB"
            )
            global_store = get_mcp_tools_store()
            post_tasks.append(global_store.store_tools(integration_id, tool_metadata))

            # 3. Index custom integration tools in ChromaDB
            if is_custom:
                custom_name = (
                    resolved.custom_doc.get("name") if resolved.custom_doc else None
                )
                custom_desc = (
                    resolved.custom_doc.get("description")
                    if resolved.custom_doc
                    else None
                )
                post_tasks.append(
                    self._handle_custom_integration_connect(
                        integration_id,
                        mcp_config.server_url,
                        tools,
                        name=custom_name,
                        description=custom_desc,
                    )
                )

            # 4. Update user integration status
            post_tasks.append(
                update_user_integration_status(
                    self.user_id, integration_id, "connected"
                )
            )

            # Execute all post-connection tasks concurrently
            results = await asyncio.gather(*post_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"[{integration_id}] Post-connection task {i} failed: {result}"
                    )

            return tools

        except Exception as e:
            error_str = str(e).lower()

            # Log comprehensive error details for debugging
            logger.error(
                f"[{integration_id}] Connection failed with exception:\n"
                f"  Error type: {type(e).__name__}\n"
                f"  Error message: {str(e)}\n"
                f"  Error repr: {repr(e)}\n"
                f"  Traceback:\n{traceback.format_exc()}"
            )

            # Check for 403 insufficient_scope per MCP spec
            # This indicates step-up authorization is needed
            if "403" in str(e) and "insufficient_scope" in error_str:
                # Try to extract required scopes from error message
                # Format: scope="required_scope1 required_scope2"
                scope_match = re.search(r'scope="([^"]+)"', str(e))
                required_scopes: list[str] = []
                if scope_match:
                    required_scopes = scope_match.group(1).split()
                logger.info(
                    f"Step-up auth required for {integration_id}, scopes: {required_scopes}"
                )
                raise StepUpAuthRequired(integration_id, required_scopes) from e

            logger.error(f"Failed to connect to MCP {integration_id}: {e}")
            # Note: Status is managed in MongoDB user_integrations, not PostgreSQL
            # PostgreSQL mcp_credentials only stores auth tokens
            raise

    async def _handle_custom_integration_connect(
        self,
        integration_id: str,
        server_url: str,
        tools: list[BaseTool],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Handle custom integration: index tools and register as subagent."""
        namespace = derive_integration_namespace(
            integration_id, server_url, is_custom=True
        )

        # Index tools in ChromaDB for semantic discovery.
        # index_tools_to_store() manages its own Redis cache (chroma:indexed:{namespace})
        # with a 24h TTL and hash-based change detection — no need to duplicate here.
        try:
            tools_with_space = [(tool, namespace) for tool in tools]
            await index_tools_to_store(tools_with_space)
        except Exception as e:
            logger.error(f"Failed to index tools in ChromaDB for {integration_id}: {e}")

        # Index as subagent for discovery via retrieve_tools
        try:
            store = await providers.aget("chroma_tools_store")
            if store:
                resolved_name = name
                resolved_description = description

                if resolved_name is None:
                    resolved = await IntegrationResolver.resolve(integration_id)
                    if resolved and resolved.custom_doc:
                        resolved_name = resolved.custom_doc.get("name", integration_id)
                        resolved_description = resolved.custom_doc.get(
                            "description", ""
                        )

                if resolved_name:
                    # Local import to avoid circular dependency
                    from app.agents.core.subagents.handoff_tools import (
                        index_custom_mcp_as_subagent,
                    )

                    await index_custom_mcp_as_subagent(
                        store=store,
                        integration_id=integration_id,
                        name=resolved_name,
                        description=resolved_description or "",
                        server_url=server_url,
                    )
                    logger.info(f"Indexed custom MCP {integration_id} as subagent")
        except Exception as e:
            logger.warning(f"Failed to index custom MCP as subagent: {e}")

    async def _try_refresh_token(
        self, integration_id: str, mcp_config: MCPConfig
    ) -> bool:
        """Attempt to refresh OAuth token using stored refresh_token."""
        oauth_config = await self._discover_oauth_config(integration_id, mcp_config)
        return await try_refresh_token(
            self.token_store, integration_id, mcp_config, oauth_config
        )

    def _resolve_client_credentials(
        self, mcp_config: MCPConfig
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve OAuth client credentials from config or environment."""
        return resolve_client_credentials(mcp_config)

    async def build_oauth_auth_url(
        self,
        integration_id: str,
        redirect_uri: str,
        redirect_path: str = "/integrations",
        challenge_data: Optional[dict] = None,
    ) -> str:
        """
        Build OAuth authorization URL using MCP spec discovery.

        1. Discovers auth server via Protected Resource Metadata
        2. Fetches Authorization Server Metadata for endpoints
        3. Tries client metadata document URL if supported (no DCR needed)
        4. Falls back to DCR on auth server if no client_id configured
        5. Returns authorization URL for browser redirect

        Supports platform integrations (from code) and custom integrations.

        Args:
            integration_id: The integration to authenticate
            redirect_uri: OAuth callback URL
            redirect_path: Frontend path to redirect after OAuth
            challenge_data: Optional pre-fetched WWW-Authenticate challenge from probe
                           to avoid duplicate discovery HTTP calls.
        """
        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"Integration {integration_id} not found")

        mcp_config = resolved.mcp_config
        # Full MCP OAuth discovery - pass challenge_data to avoid re-probe
        oauth_config = await self._discover_oauth_config(
            integration_id, mcp_config, challenge_data=challenge_data
        )

        # Resolve client credentials with the following priority order per MCP spec:
        # 1. Pre-configured credentials (from MCPConfig or env vars)
        # 2. Stored DCR client (from PostgreSQL, saved during previous _register_client)
        # 3. Client Metadata Document URL (when AS supports it and API is non-localhost)
        # 4. Dynamic Client Registration (DCR) as last resort
        client_id, client_secret = self._resolve_client_credentials(mcp_config)

        if not client_id:
            # Priority 2: Check for stored DCR client from a previous registration.
            # This is effectively "pre-registered" for this specific integration.
            dcr_data = await self.token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
                logger.debug(f"Using stored DCR client for {integration_id}")

        if not client_id:
            # Priority 3: Use Client ID Metadata Document if supported.
            # Per draft-ietf-oauth-client-id-metadata-document, the client_id
            # can be the URL to the client metadata document.
            #
            # IMPORTANT: Only use client metadata document when our API is publicly
            # accessible. The auth server needs to fetch our metadata document to
            # validate the client. When running on localhost, this is impossible.
            api_base = get_api_base_url()
            is_localhost = is_localhost_url(api_base)

            if (
                oauth_config.get("client_id_metadata_document_supported")
                and not is_localhost
            ):
                client_id = get_client_metadata_document_url(api_base)
                logger.info(
                    f"Using client metadata document URL as client_id for {integration_id}: {client_id}"
                )
            # Priority 4: Fall back to Dynamic Client Registration (DCR).
            # Also required when running locally since the auth server
            # cannot reach localhost to validate the client metadata document.
            elif oauth_config.get("registration_endpoint"):
                client_id = await self._register_client(
                    integration_id,
                    oauth_config["registration_endpoint"],
                    redirect_uri,
                )
                logger.info(f"Registered new client via DCR for {integration_id}")

        if not client_id:
            raise ValueError(
                f"Could not obtain client_id for {integration_id}. "
                "Tried: (1) pre-configured credentials, (2) stored DCR client, "
                "(3) client metadata document, (4) new DCR registration. "
                "The authorization server may require manual client pre-registration."
            )

        logger.info(f"[{integration_id}] client_id resolved for auth URL")

        # Verify PKCE support per MCP spec using centralized validation
        validate_pkce_support(oauth_config, integration_id)

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

        # NEW: Add nonce for OpenID Connect flows to prevent replay attacks
        if scope_str and "openid" in scope_str.lower():
            nonce = secrets.token_urlsafe(16)
            params["nonce"] = nonce
            # Store nonce for validation in callback
            await self.token_store.store_oauth_nonce(integration_id, nonce)
            logger.debug(f"Added OIDC nonce for {integration_id}")

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
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(
                    registration_endpoint,
                    json={
                        "client_name": "GAIA",
                        "redirect_uris": [redirect_uri],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "token_endpoint_auth_method": "none",  # nosec B105 - OAuth spec requires literal "none"
                    },
                    headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
                    timeout=30,
                )

                # Check for DCR not supported (403/404/405)
                if response.status_code in (403, 404, 405):
                    raise DCRNotSupportedException(
                        f"DCR not supported at {registration_endpoint} "
                        f"(status {response.status_code}). Pre-registration required."
                    )

                response.raise_for_status()
                dcr_data = response.json()
                await self.token_store.store_dcr_client(integration_id, dcr_data)
                logger.info(
                    f"DCR successful for {integration_id} at {registration_endpoint}"
                )
                return dcr_data.get("client_id")
        except DCRNotSupportedException:
            raise  # Re-raise without wrapping
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
        """
        Exchange authorization code for tokens and connect.

        Implements RFC 6749 token exchange with:
        - PKCE code_verifier (RFC 7636)
        - Resource binding (RFC 8707)
        - Structured error parsing
        - Token response validation
        - JWT issuer validation (when applicable)
        """
        is_valid, code_verifier = await self.token_store.verify_oauth_state(
            integration_id, state
        )
        if not is_valid:
            raise ValueError(
                "Invalid OAuth state - possible CSRF attack or expired state"
            )

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

        # Validate token endpoint uses HTTPS
        try:
            validate_https_url(token_endpoint)
        except OAuthSecurityError as e:
            logger.warning(f"Token endpoint security warning: {e}")

        # Resolve client credentials using same priority as build_oauth_auth_url
        # to ensure the same client_id is used for both authorization and token exchange.
        #
        # Priority order (must match build_oauth_auth_url):
        # 1. Pre-configured credentials (from MCPConfig or env vars)
        # 2. Stored DCR client (from PostgreSQL, saved during _register_client)
        # 3. Client Metadata Document URL (when AS supports it, non-localhost)
        client_id = None
        client_secret = None

        # 1. Pre-configured credentials
        resolved_id, resolved_secret = self._resolve_client_credentials(mcp_config)
        if resolved_id:
            client_id = resolved_id
            client_secret = resolved_secret

        # 2. Stored DCR client
        if not client_id:
            dcr_data = await self.token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
                client_secret = dcr_data.get("client_secret")

        # 3. Client Metadata Document URL (must match build_oauth_auth_url logic)
        # Priority 3: Client Metadata Document URL (must match build_oauth_auth_url logic)
        if not client_id:
            api_base = get_api_base_url()
            is_localhost = is_localhost_url(api_base)
            if (
                oauth_config.get("client_id_metadata_document_supported")
                and not is_localhost
            ):
                client_id = get_client_metadata_document_url(api_base)
                logger.info(
                    f"Using client metadata document URL as client_id "
                    f"for token exchange: {client_id}"
                )

        if not client_id:
            raise ValueError(
                f"Could not resolve client_id for token exchange ({integration_id}). "
                "No pre-configured credentials, no DCR registration, "
                "and client metadata document not applicable."
            )

        logger.info(
            f"[{integration_id}] client_id resolved for token exchange: "
            f"client_id={client_id[:50]}{'...' if len(client_id) > 50 else ''}, "
            f"has_secret={client_secret is not None}"
        )

        # Get resource for token binding (RFC 8707)
        resource = oauth_config.get("resource", mcp_config.server_url.rstrip("/"))

        # Exchange code for tokens
        async with httpx.AsyncClient() as http_client:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "resource": resource,  # CRITICAL: Bind token to MCP server (RFC 8707)
            }

            # Include PKCE code_verifier if we have it (required for OAuth 2.1)
            if code_verifier:
                token_data["code_verifier"] = code_verifier

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            }

            # Always include client_id in body for PKCE compatibility
            # Some OAuth servers require client_id in body for PKCE validation
            token_data["client_id"] = client_id

            if client_secret:
                credentials = f"{client_id}:{client_secret}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"

            response = await http_client.post(
                token_endpoint, data=token_data, headers=headers, timeout=30
            )

            # Handle error responses with structured parsing
            # Accept any 2xx status code as success (OAuth servers vary: 200, 201, etc.)
            if not (200 <= response.status_code < 300):
                error_info = parse_oauth_error_response(response)
                logger.error(
                    f"Token exchange failed for {integration_id}: "
                    f"{error_info['error']} - {error_info.get('error_description')}"
                )
                raise ValueError(
                    f"Token exchange failed: {error_info['error']} - "
                    f"{error_info.get('error_description', 'Unknown error')}"
                )

            tokens = response.json()

        # Validate token response per OAuth 2.1 spec
        validate_token_response(tokens, integration_id)
        access_token = tokens["access_token"]

        # Validate JWT issuer if applicable
        issuer = oauth_config.get("issuer")
        if issuer:
            if not validate_jwt_issuer(access_token, issuer, integration_id):
                logger.warning(f"JWT issuer validation failed for {integration_id}")
                # Continue anyway - some tokens are opaque, not JWTs

        # Validate OIDC nonce if one was stored during auth URL build
        stored_nonce = await self.token_store.get_and_delete_oauth_nonce(integration_id)
        if stored_nonce:
            id_token = tokens.get("id_token")
            if id_token:
                try:
                    # Decode JWT payload without verification (nonce is for replay protection)
                    payload_b64 = id_token.split(".")[1]
                    # Add padding
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
                    token_nonce = payload.get("nonce")
                except Exception as e:
                    logger.warning(
                        f"Could not decode id_token for nonce validation ({integration_id}): {e}"
                    )
                    token_nonce = None
                if token_nonce is not None and token_nonce != stored_nonce:
                    raise ValueError(
                        f"OIDC nonce mismatch for {integration_id}: "
                        "possible replay attack"
                    )
                if token_nonce is not None:
                    logger.debug(f"OIDC nonce validated for {integration_id}")
            else:
                logger.warning(
                    f"OIDC nonce stored but no id_token in response for {integration_id}"
                )

        # Calculate expiry time if provided
        expires_at = None
        if tokens.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=tokens["expires_in"]
            )

        # Handle refresh token rotation (new refresh_token may be issued)
        new_refresh_token = tokens.get("refresh_token")

        logger.info(
            f"[{integration_id}] OAuth callback - token exchange successful. "
            f"access_token length={len(access_token)}, "
            f"has_refresh_token={new_refresh_token is not None}, "
            f"expires_at={expires_at}"
        )

        # Store tokens
        logger.info(f"[{integration_id}] Storing OAuth tokens to PostgreSQL")
        await self.token_store.store_oauth_tokens(
            integration_id=integration_id,
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_at=expires_at,
        )
        logger.info(
            f"[{integration_id}] Tokens stored successfully with status=connected"
        )

        # Connect using the newly obtained tokens
        # If connection fails, clean up stored tokens to prevent stuck state
        logger.info(f"[{integration_id}] Attempting connection with stored tokens")
        try:
            tools = await self.connect(integration_id)
            logger.info(
                f"[{integration_id}] Connection succeeded after OAuth callback, got {len(tools)} tools"
            )
            return tools
        except Exception as e:
            is_auth_error = "401" in str(e) or "authentication" in str(e).lower()
            logger.error(
                f"[{integration_id}] Connection failed after token storage:\n"
                f"  Error type: {type(e).__name__}\n"
                f"  Error message: {str(e)}\n"
                f"  Error repr: {repr(e)}\n"
                f"  Is auth error: {is_auth_error}\n"
                f"  This may indicate mcp-use is ignoring our stored token.\n"
                f"  Rolling back tokens to prevent stuck state.\n"
                f"  Traceback:\n{traceback.format_exc()}"
            )
            # Delete the tokens we just stored since connection failed
            await self.token_store.delete_credentials(integration_id)
            raise

    async def disconnect(self, integration_id: str) -> None:
        """
        Disconnect from an MCP server.

        Performs:
        1. Token revocation at authorization server (RFC 7009)
        2. In-memory client cleanup
        3. OAuth discovery cache cleanup
        4. Credential deletion from PostgreSQL
        """
        # First, revoke tokens at authorization server (RFC 7009)
        await self._revoke_tokens(integration_id)

        # Clean up in-memory state
        if integration_id in self._clients:
            try:
                await self._clients[integration_id].close_all_sessions()
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")
            del self._clients[integration_id]

        if integration_id in self._tools:
            del self._tools[integration_id]

        # Clear OAuth discovery cache
        try:
            await delete_cache(f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}")
        except Exception as e:
            logger.warning(f"Failed to clear OAuth discovery cache: {e}")

        # Remove tool metadata from MongoDB so ghost tools don't appear
        try:
            await integrations_collection.update_one(
                {"integration_id": integration_id},
                {"$unset": {"tools": ""}},
            )
            # Invalidate the global MCP tools Redis cache
            await delete_cache(MCP_TOOLS_CACHE_KEY)
        except Exception as e:
            logger.warning(f"Failed to clear MongoDB tools for {integration_id}: {e}")

        # Invalidate ChromaDB namespace cache so tools are re-indexed on reconnect
        try:
            resolved = await IntegrationResolver.resolve(integration_id)
            if resolved and resolved.mcp_config:
                server_url = resolved.mcp_config.server_url or ""
                is_custom = resolved.source == "custom"
                namespace = derive_integration_namespace(
                    integration_id, server_url, is_custom=is_custom
                )
                await delete_cache(f"chroma:indexed:{namespace}")
        except Exception as e:
            logger.warning(f"Failed to invalidate ChromaDB cache: {e}")

        # Delete credentials from PostgreSQL (for both authenticated and unauthenticated MCPs)
        await self.token_store.delete_credentials(integration_id)

        logger.info(f"Disconnected MCP {integration_id}")

    async def _revoke_tokens(self, integration_id: str) -> None:
        """Revoke OAuth tokens at authorization server per RFC 7009."""
        try:
            oauth_config = await self.token_store.get_oauth_discovery(integration_id)
            if not oauth_config:
                return

            resolved = await IntegrationResolver.resolve(integration_id)
            mcp_config = resolved.mcp_config if resolved else None
            if mcp_config:
                await revoke_tokens(
                    self.token_store, integration_id, mcp_config, oauth_config
                )
        except Exception as e:
            logger.warning(f"Token revocation failed for {integration_id}: {e}")

    async def get_tools(self, integration_id: str) -> list[BaseTool]:
        """Get tools for a connected integration."""
        return self._tools.get(integration_id, [])

    async def health_check(self, integration_id: str) -> dict:
        """
        Check MCP connection health.

        Performs a lightweight operation (list_tools) to verify the connection
        is still active and responsive.

        Args:
            integration_id: The integration to health check

        Returns:
            {
                "status": "healthy" | "unhealthy" | "disconnected",
                "latency_ms": int,  # Round-trip time in milliseconds
                "error": str,  # Only present if unhealthy
            }
        """
        if integration_id not in self._clients:
            return {"status": "disconnected", "latency_ms": 0}

        client = self._clients[integration_id]

        try:
            start = time.monotonic()
            # Use list_tools as lightweight health check - it's fast and doesn't mutate state
            session = client.get_session(integration_id)
            await session.list_tools()
            latency_ms = int((time.monotonic() - start) * 1000)

            return {"status": "healthy", "latency_ms": latency_ms}

        except Exception as e:
            logger.warning(f"Health check failed for {integration_id}: {e}")
            return {"status": "unhealthy", "latency_ms": 0, "error": str(e)}

    def is_connected(self, integration_id: str) -> bool:
        """Check if an integration is connected (in memory)."""
        return integration_id in self._clients

    async def is_connected_db(self, integration_id: str) -> bool:
        """Check if integration is connected (in MongoDB user_integrations)."""
        doc = await user_integrations_collection.find_one(
            {
                "user_id": self.user_id,
                "integration_id": integration_id,
                "status": "connected",
            }
        )
        return doc is not None

    async def _safe_connect(self, integration_id: str) -> list[BaseTool] | None:
        """Connect with error handling for parallel execution."""
        try:
            return await self.connect(integration_id)
        except Exception as e:
            logger.warning(f"Failed to connect MCP {integration_id}: {e}")
            return None

    async def get_all_connected_tools(self) -> dict[str, list[BaseTool]]:
        """
        Get tools from all connected MCP integrations for this user.

        Connects to all uncached integrations in parallel using asyncio.gather().
        Cached tools are returned from memory if already connected.

        Data Source:
        - MongoDB user_integrations (single source of truth for connection status)

        Returns dict mapping integration_id -> list of tools.
        """
        # Get all connected integrations from MongoDB (single source of truth)
        connected_ids: list[str] = []
        try:
            user_integrations = await get_user_connected_integrations(self.user_id)
            connected_ids = [
                str(ui.get("integration_id"))
                for ui in user_integrations
                if ui.get("integration_id") is not None
            ]
        except Exception as e:
            logger.warning(f"Failed to get connected MCPs from user_integrations: {e}")

        all_tools: dict[str, list[BaseTool]] = {}

        # Separate cached vs needs-connection
        to_resolve: list[str] = []
        for integration_id in connected_ids:
            if integration_id in self._tools:
                all_tools[integration_id] = self._tools[integration_id]
            else:
                to_resolve.append(integration_id)

        if not to_resolve:
            return all_tools

        # Resolve all integrations in parallel to filter non-MCP ones
        resolved_list = await asyncio.gather(
            *[IntegrationResolver.resolve(iid) for iid in to_resolve]
        )

        mcp_ids = [
            iid
            for iid, resolved in zip(to_resolve, resolved_list)
            if resolved and resolved.mcp_config
        ]

        if not mcp_ids:
            return all_tools

        # Connect all MCP integrations in parallel
        logger.info(f"Connecting {len(mcp_ids)} MCP integrations in parallel")
        results = await asyncio.gather(*[self._safe_connect(iid) for iid in mcp_ids])

        for integration_id, tools in zip(mcp_ids, results):
            if tools:
                all_tools[integration_id] = tools

        return all_tools

    async def ensure_connected(self, integration_id: str) -> list[BaseTool]:
        """
        Ensure connection to an MCP server, reconnecting if needed.

        Uses stored tokens to reconnect if not already connected in memory.
        Connection status checked against MongoDB user_integrations.
        """
        # Already connected in memory
        if integration_id in self._tools:
            return self._tools[integration_id]

        # Check if connected in MongoDB (single source of truth)
        if await self.is_connected_db(integration_id):
            return await self.connect(integration_id)

        # Not connected at all
        raise ValueError(
            f"MCP {integration_id} not connected. User needs to complete OAuth flow."
        )

    async def ensure_token_valid(self, integration_id: str) -> None:
        """Proactively refresh token if expiring soon.

        Called before tool invocation to prevent 401 errors.
        This is a no-op for unauthenticated integrations.
        """
        # Check if we have credentials for this integration
        if not await self.token_store.has_credentials(integration_id):
            return  # No auth required or no stored credentials

        # Check if token is expiring soon
        if await self.token_store.is_token_expiring_soon(integration_id):
            logger.info(
                f"Token expiring soon for {integration_id}, proactively refreshing"
            )
            resolved = await IntegrationResolver.resolve(integration_id)
            if resolved and resolved.mcp_config:
                refreshed = await self._try_refresh_token(
                    integration_id, resolved.mcp_config
                )
                if not refreshed:
                    logger.warning(
                        f"Proactive token refresh failed for {integration_id}"
                    )

    async def try_token_refresh(self, integration_id: str) -> bool:
        """Attempt to refresh OAuth token.

        Public wrapper for token refresh - used by stub executor on 401 errors.
        After a successful refresh, the stale in-memory session is evicted so the
        next connect() creates a fresh session with the new token.

        Returns True if refresh succeeded, False otherwise.
        """
        resolved = await IntegrationResolver.resolve(integration_id)
        if resolved and resolved.mcp_config and resolved.mcp_config.requires_auth:
            refreshed = await self._try_refresh_token(
                integration_id, resolved.mcp_config
            )
            if refreshed:
                # Evict stale client/tools so next connect() uses the new token
                if integration_id in self._clients:
                    try:
                        await self._clients[integration_id].close_all_sessions()
                    except Exception as e:
                        logger.warning(
                            f"[{integration_id}] Error closing stale session after refresh: {e}"
                        )
                    self._clients.pop(integration_id, None)
                self._tools.pop(integration_id, None)
            return refreshed
        return False

    async def _safe_close_client(self, client: BaseMCPClient) -> None:
        """Close a BaseMCPClient session, swallowing errors."""
        try:
            await client.close_all_sessions()
        except Exception as e:
            logger.warning(f"Error closing MCP client session: {e}")

    async def close_all_client_sessions(self) -> None:
        """Close all active MCP client sessions.

        Public method for graceful shutdown - used by MCPClientPool.
        """
        for integration_id in list(self._clients.keys()):
            try:
                await self._clients[integration_id].close_all_sessions()
            except Exception as e:
                logger.warning(f"Error closing MCP session for {integration_id}: {e}")

    def get_active_integration_ids(self) -> list[str]:
        """Get list of active integration IDs.

        Public method for introspection - used by MCPClientPool.
        """
        return list(self._clients.keys())


async def get_mcp_client(user_id: str) -> MCPClient:
    """Get MCP client for a user from the pool."""
    pool = await get_mcp_client_pool()
    return await pool.get(user_id)
