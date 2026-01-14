"""
MCP Client wrapper.

Implements complete MCP OAuth 2.1 authorization flow per specification.
See: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
"""

import base64
import re
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
        self,
        integration_id: str,
        mcp_config: MCPConfig,
        challenge_data: Optional[dict] = None,
    ) -> dict:
        """
        Full MCP OAuth discovery flow per specification.

        Args:
            integration_id: The integration identifier
            mcp_config: MCP configuration with server URL
            challenge_data: Optional pre-fetched WWW-Authenticate challenge (avoids re-probe)

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

        # Phase 1: Use provided challenge or probe server for WWW-Authenticate
        # If challenge_data was passed (from prior probe), use it to avoid duplicate HTTP call
        challenge = challenge_data or await extract_auth_challenge(server_url)
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
                "code_challenge_methods_supported": auth_metadata.get(
                    "code_challenge_methods_supported", []
                ),
                "client_id_metadata_document_supported": auth_metadata.get(
                    "client_id_metadata_document_supported", False
                ),
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
                "code_challenge_methods_supported": auth_metadata.get(
                    "code_challenge_methods_supported", []
                ),
                "client_id_metadata_document_supported": auth_metadata.get(
                    "client_id_metadata_document_supported", False
                ),
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
        """Build mcp-use config dict.

        When auth is a string token, mcp-use uses BearerAuth directly
        without OAuth discovery. This is the proper way to pass
        already-obtained tokens to mcp-use.
        """
        server_config: dict = {"url": mcp_config.server_url}

        if mcp_config.transport:
            server_config["transport"] = mcp_config.transport

        # Check for stored OAuth token if auth is required
        if mcp_config.requires_auth:
            # Check if token is expiring soon and try to refresh
            if await self.token_store.is_token_expiring_soon(integration_id):
                logger.info(
                    f"Token expiring soon for {integration_id}, attempting refresh"
                )
                await self._try_refresh_token(integration_id, mcp_config)

            stored_token = await self.token_store.get_oauth_token(integration_id)
            if stored_token:
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
            else:
                logger.warning(
                    f"No valid OAuth token for {integration_id} - connection may fail"
                )
        else:
            # CRITICAL: Explicitly set auth to None to prevent mcp-use from
            # defaulting to {} which triggers OAuth discovery and causes lag.
            # When auth is None, HttpConnector skips OAuth initialization entirely.
            server_config["auth"] = None

        return {"mcpServers": {integration_id: server_config}}

    async def connect(self, integration_id: str) -> list[BaseTool]:
        """
        Connect to an MCP server and return LangChain tools.

        For unauthenticated MCPs: Connects directly.
        For OAuth MCPs: Uses stored credentials from completed OAuth flow.
        Supports platform integrations (from code) and custom integrations.
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

            # For unauthenticated MCPs, record connection in PostgreSQL (Issue 4.1 fix)
            if not mcp_config.requires_auth:
                await self.token_store.store_unauthenticated(integration_id)

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
                custom_name = (
                    resolved.custom_doc.get("name") if resolved.custom_doc else None
                )
                custom_desc = (
                    resolved.custom_doc.get("description")
                    if resolved.custom_doc
                    else None
                )
                await self._handle_custom_integration_connect(
                    integration_id,
                    mcp_config.server_url,
                    tools,
                    name=custom_name,
                    description=custom_desc,
                )

            # Update user integration status to connected
            # Import here to avoid circular dependency
            from app.services.integration_service import update_user_integration_status

            try:
                await update_user_integration_status(
                    self.user_id, integration_id, "connected"
                )
            except Exception as status_err:
                # Best-effort: log but don't fail if MongoDB update fails
                logger.warning(
                    f"MongoDB status update failed for {integration_id}: {status_err}"
                )

            return tools

        except Exception as e:
            error_str = str(e).lower()

            # Check for 403 insufficient_scope per MCP spec
            # This indicates step-up authorization is needed
            if "403" in str(e) and "insufficient_scope" in error_str:
                # Try to extract required scopes from error message
                # Format: scope="required_scope1 required_scope2"
                scope_match = re.search(r'scope="([^"]+)"', str(e))
                required_scopes = []
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
        # Index tools in ChromaDB for semantic discovery
        try:
            from app.db.chroma.chroma_tools_store import index_tools_to_store

            tools_with_space = [(tool, integration_id) for tool in tools]
            await index_tools_to_store(tools_with_space)
        except Exception as e:
            logger.warning(
                f"Failed to index tools in ChromaDB for {integration_id}: {e}"
            )

        # Index as subagent for discovery via retrieve_tools
        try:
            from app.agents.core.subagents.handoff_tools import (
                index_custom_mcp_as_subagent,
            )
            from app.core.lazy_loader import providers

            store = await providers.aget("chroma_tools_store")
            if store:
                resolved_name = name
                resolved_description = description

                if resolved_name is None:
                    from app.services.integration_resolver import IntegrationResolver

                    resolved = await IntegrationResolver.resolve(integration_id)
                    if resolved and resolved.custom_doc:
                        resolved_name = resolved.custom_doc.get("name", integration_id)
                        resolved_description = resolved.custom_doc.get(
                            "description", ""
                        )

                if resolved_name:
                    await index_custom_mcp_as_subagent(
                        store=store,
                        integration_id=integration_id,
                        name=resolved_name,
                        description=resolved_description or "",
                    )
                    logger.info(f"Indexed custom MCP {integration_id} as subagent")
        except Exception as e:
            logger.warning(f"Failed to index custom MCP as subagent: {e}")

    async def _try_refresh_token(
        self, integration_id: str, mcp_config: MCPConfig
    ) -> bool:
        """
        Attempt to refresh OAuth token using stored refresh_token.

        Returns True if refresh succeeded, False otherwise.
        """
        refresh_token = await self.token_store.get_refresh_token(integration_id)
        if not refresh_token:
            logger.debug(f"No refresh token for {integration_id}")
            return False

        try:
            # Get OAuth discovery for token endpoint
            oauth_config = await self._discover_oauth_config(integration_id, mcp_config)
            token_endpoint = oauth_config.get("token_endpoint")
            if not token_endpoint:
                return False

            # Get client credentials
            client_id, client_secret = self._resolve_client_credentials(mcp_config)
            if not client_id:
                dcr_data = await self.token_store.get_dcr_client(integration_id)
                if dcr_data:
                    client_id = dcr_data.get("client_id")
                    client_secret = dcr_data.get("client_secret")

            if not client_id:
                return False

            # RFC 8707: resource parameter required for token binding
            resource = oauth_config.get("resource", mcp_config.server_url.rstrip("/"))

            async with httpx.AsyncClient() as client:
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

                response = await client.post(
                    token_endpoint, data=token_data, headers=headers, timeout=30
                )

                if response.status_code != 200:
                    logger.warning(f"Token refresh failed for {integration_id}")
                    return False

                tokens = response.json()

                # Calculate new expiry
                expires_at = None
                if tokens.get("expires_in"):
                    from datetime import datetime, timedelta, timezone

                    expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=tokens["expires_in"]
                    )

                # Store refreshed tokens
                await self.token_store.store_oauth_tokens(
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
        challenge_data: Optional[dict] = None,
    ) -> str:
        """
        Build OAuth authorization URL using MCP spec discovery.

        1. Discovers auth server via Protected Resource Metadata
        2. Fetches Authorization Server Metadata for endpoints
        3. Uses DCR on auth server if no client_id configured
        4. Returns authorization URL for browser redirect

        Supports platform integrations (from code) and custom integrations.

        Args:
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

        # Get or register client credentials
        client_id, client_secret = self._resolve_client_credentials(mcp_config)

        if not client_id:
            # Try stored DCR client
            dcr_data = await self.token_store.get_dcr_client(integration_id)
            if dcr_data:
                client_id = dcr_data.get("client_id")
            elif oauth_config.get("registration_endpoint"):
                # Dynamic Client Registration (DCR)
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

        # Verify PKCE support per MCP spec
        # MCP clients MUST verify code_challenge_methods_supported contains S256
        # If field is absent, assume PKCE is supported (per RFC 8414 Section 5)
        pkce_methods = oauth_config.get("code_challenge_methods_supported", [])
        if pkce_methods and "S256" not in pkce_methods:
            raise ValueError(
                f"Server {integration_id} does not support S256 PKCE method. "
                f"Supported methods: {pkce_methods}. MCP requires S256."
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
            from app.utils.mcp_oauth_utils import MCP_PROTOCOL_VERSION

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

        # Validate token response per OAuth 2.1 spec (Issue 3.2 fix)
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("Token response missing access_token")

        token_type = tokens.get("token_type", "")
        if token_type.lower() != "bearer":
            logger.warning(
                f"Unexpected token_type '{token_type}' for {integration_id}, expected 'Bearer'"
            )

        # Calculate expiry time if provided
        expires_at = None
        if tokens.get("expires_in"):
            from datetime import datetime, timedelta, timezone

            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=tokens["expires_in"]
            )

        # Store tokens
        await self.token_store.store_oauth_tokens(
            integration_id=integration_id,
            access_token=access_token,
            refresh_token=tokens.get("refresh_token"),
            expires_at=expires_at,
        )

        # Connect using the newly obtained tokens
        # If connection fails, clean up stored tokens to prevent stuck state
        try:
            return await self.connect(integration_id)
        except Exception as e:
            is_auth_error = "401" in str(e) or "authentication" in str(e).lower()
            logger.error(
                f"Connection failed after token storage for {integration_id}: {e}. "
                f"Auth error: {is_auth_error}. "
                f"This may indicate mcp-use is ignoring our stored token. "
                "Rolling back tokens to prevent stuck state."
            )
            # Delete the tokens we just stored since connection failed
            await self.token_store.delete_credentials(integration_id)
            raise

    async def disconnect(self, integration_id: str) -> None:
        """Disconnect from an MCP server."""
        # Always clean up in-memory state
        if integration_id in self._clients:
            try:
                await self._clients[integration_id].close_all_sessions()
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")
            del self._clients[integration_id]

        if integration_id in self._tools:
            del self._tools[integration_id]

        # Clear OAuth discovery cache (Issue 4.2 fix)
        from app.constants.mcp import OAUTH_DISCOVERY_PREFIX
        from app.db.redis import delete_cache

        try:
            await delete_cache(f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}")
        except Exception as e:
            logger.warning(f"Failed to clear OAuth discovery cache: {e}")

        # Delete credentials from PostgreSQL (for both authenticated and unauthenticated MCPs)
        await self.token_store.delete_credentials(integration_id)

        logger.info(f"Disconnected MCP {integration_id}")

    async def get_tools(self, integration_id: str) -> list[BaseTool]:
        """Get tools for a connected integration."""
        return self._tools.get(integration_id, [])

    def is_connected(self, integration_id: str) -> bool:
        """Check if an integration is connected (in memory)."""
        return integration_id in self._clients

    async def is_connected_db(self, integration_id: str) -> bool:
        """Check if integration is connected (in MongoDB user_integrations)."""
        from app.db.mongodb.collections import user_integrations_collection

        doc = await user_integrations_collection.find_one(
            {
                "user_id": self.user_id,
                "integration_id": integration_id,
                "status": "connected",
            }
        )
        return doc is not None

    async def get_all_connected_tools(self) -> dict[str, list[BaseTool]]:
        """
        Get tools from all connected MCP integrations for this user.

        Always connects to get real tools with proper schemas.
        Cached tools are returned from memory if already connected.

        Data Source:
        - MongoDB user_integrations (single source of truth for connection status)

        Returns dict mapping integration_id -> list of tools.
        """
        # Get all connected integrations from MongoDB (single source of truth)
        from app.services.integration_service import get_user_connected_integrations

        connected_ids: list[str] = []
        try:
            user_integrations = await get_user_connected_integrations(self.user_id)
            connected_ids = [
                ui.get("integration_id")
                for ui in user_integrations
                if ui.get("integration_id")
            ]
        except Exception as e:
            logger.warning(f"Failed to get connected MCPs from user_integrations: {e}")

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

        Returns True if refresh succeeded, False otherwise.
        """
        resolved = await IntegrationResolver.resolve(integration_id)
        if resolved and resolved.mcp_config and resolved.mcp_config.requires_auth:
            return await self._try_refresh_token(integration_id, resolved.mcp_config)
        return False


async def get_mcp_client(user_id: str) -> MCPClient:
    """Get MCP client for a user from the pool."""
    from app.services.mcp.mcp_client_pool import get_mcp_client_pool

    pool = await get_mcp_client_pool()
    return await pool.get(user_id)
