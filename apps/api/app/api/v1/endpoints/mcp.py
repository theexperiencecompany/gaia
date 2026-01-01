"""
MCP Integration API Routes.

Handles MCP connection, OAuth callbacks, disconnection, and tool discovery.
Routes follow same patterns as integrations.py for Composio parity.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.config.settings import settings
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_token_store import MCPTokenStore

router = APIRouter()


class MCPConnectRequest(BaseModel):
    """Request body for MCP connection."""

    bearer_token: Optional[str] = None


class MCPConnectResponse(BaseModel):
    """Response for MCP connection."""

    status: str
    integration_id: str
    tools_count: int
    redirect_url: Optional[str] = None
    message: Optional[str] = None


class MCPToolInfo(BaseModel):
    """Individual tool information."""

    name: str
    description: Optional[str] = None


class MCPToolsResponse(BaseModel):
    """Response for tools endpoint."""

    tools: list[MCPToolInfo]
    connected: bool


class MCPIntegrationStatus(BaseModel):
    """Status of a single MCP integration."""

    integrationId: str
    connected: bool
    status: str


class MCPStatusResponse(BaseModel):
    """Response for status endpoint."""

    integrations: list[MCPIntegrationStatus]


@router.get("/connect/{integration_id}")
async def connect_mcp_oauth(
    integration_id: str,
    redirect_path: str = Query("/integrations"),
    user: dict = Depends(get_current_user),
):
    """
    Initiate OAuth flow for an MCP integration via browser redirect.

    This endpoint is for MCP integrations that require authentication.
    For unauthenticated MCPs, use POST /connect/{integration_id}.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    integration = get_integration_by_id(integration_id)
    if not integration or integration.managed_by != "mcp":
        raise HTTPException(
            status_code=404, detail=f"MCP integration {integration_id} not found"
        )

    mcp_config = integration.mcp_config
    if not mcp_config:
        raise HTTPException(status_code=400, detail="MCP config missing")

    # Only auth-required integrations should use this endpoint
    if not mcp_config.requires_auth:
        raise HTTPException(
            status_code=400,
            detail=f"Use POST /api/v1/mcp/connect/{integration_id} for unauthenticated integrations",
        )

    client = get_mcp_client(user_id=str(user_id))

    try:
        # Build OAuth authorization URL and redirect
        auth_url = await client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{_get_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path=redirect_path,
        )
        return RedirectResponse(url=auth_url)

    except Exception as e:
        logger.error(f"OAuth initiation failed for {integration_id}: {e}")
        frontend_url = _get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={str(e)}"
        )


def _get_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return getattr(settings, "API_BASE_URL", "http://localhost:8000")


def _get_frontend_url() -> str:
    """Get the frontend base URL for redirects."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


@router.post("/connect/{integration_id}", response_model=MCPConnectResponse)
async def connect_mcp(
    integration_id: str,
    request: MCPConnectRequest,
    user: dict = Depends(get_current_user),
):
    """
    Connect to an MCP integration.

    For unauthenticated MCPs - they're always available, no action needed.
    For OAuth MCPs - use GET /connect/{integration_id} instead (browser redirect).
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    integration = get_integration_by_id(integration_id)
    if not integration or integration.managed_by != "mcp":
        raise HTTPException(
            status_code=404, detail=f"MCP integration {integration_id} not found"
        )

    mcp_config = integration.mcp_config
    if not mcp_config:
        raise HTTPException(status_code=400, detail="MCP config missing")

    # OAuth-required MCPs should use GET endpoint for browser redirect
    if mcp_config.requires_auth:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth integrations require browser redirect. Use GET /api/v1/mcp/connect/{integration_id}",
        )

    # Unauthenticated MCPs are always available - no connection needed
    return MCPConnectResponse(
        status="connected",
        integration_id=integration_id,
        tools_count=0,  # Tools discovered lazily
        message=f"{integration.name} is always available - no connection needed",
    )


@router.get("/oauth/callback")
async def mcp_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """Handle OAuth callback from MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    # Parse state: "token:integration_id:redirect_path"
    try:
        parts = state.split(":", 2)
        if len(parts) < 2:
            raise ValueError("Invalid state format")
        state_token = parts[0]
        integration_id = parts[1]
        redirect_path = parts[2] if len(parts) > 2 else "/integrations"
    except Exception as e:
        logger.error(f"Failed to parse OAuth state: {e}")
        frontend_url = _get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}/integrations?status=failed&error=invalid_state"
        )

    client = get_mcp_client(user_id=str(user_id))

    try:
        await client.handle_oauth_callback(
            integration_id=integration_id,
            code=code,
            state=state_token,
            redirect_uri=f"{_get_base_url()}/api/v1/mcp/oauth/callback",
        )

        # Fetch and cache tools immediately after successful OAuth
        # client.connect() handles caching with full args_schema
        try:
            tools = await client.connect(integration_id)
            if tools:
                logger.info(
                    f"Connected and cached {len(tools)} tools for {integration_id} after OAuth"
                )

                # Index tools to ChromaDB for semantic search
                tool_registry = await get_tool_registry()
                await tool_registry.load_user_mcp_tools(str(user_id))
                logger.info(f"Indexed MCP tools from {integration_id} to ChromaDB")

                # Invalidate tools list cache so frontend sees new tools immediately
                try:
                    await delete_cache("get_available_tools:*")
                    logger.info("Invalidated tools list cache after MCP connection")
                except Exception as cache_err:
                    logger.warning(f"Failed to invalidate tools cache: {cache_err}")
        except Exception as tool_err:
            # Don't fail the OAuth flow if tool caching fails
            logger.warning(f"Failed to cache tools for {integration_id}: {tool_err}")

        # Invalidate status cache for parity
        await _invalidate_status_cache(str(user_id))

        # Redirect to integrations page with success
        frontend_url = _get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=connected"
        )

    except Exception as e:
        logger.error(f"OAuth callback failed for {integration_id}: {e}")
        frontend_url = _get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={str(e)}"
        )


@router.delete("/{integration_id}")
async def disconnect_mcp_integration(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """Disconnect an MCP integration."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    # Check if this is an unauthenticated MCP - they can't be disconnected
    integration = get_integration_by_id(integration_id)
    if (
        integration
        and integration.mcp_config
        and not integration.mcp_config.requires_auth
    ):
        raise HTTPException(
            status_code=400,
            detail=f"{integration.name} is always available and cannot be disconnected",
        )

    client = get_mcp_client(user_id=str(user_id))
    await client.disconnect(integration_id)

    # Invalidate status cache for parity
    await _invalidate_status_cache(str(user_id))

    return JSONResponse(
        content={"status": "success", "message": f"Disconnected {integration_id}"}
    )


@router.get("/tools/{integration_id}", response_model=MCPToolsResponse)
async def get_mcp_tools(
    integration_id: str,
    user: dict = Depends(get_current_user),
) -> MCPToolsResponse:
    """
    Get discovered tools for an MCP integration.

    For auth-required MCPs, returns cached tools from when user first connected.
    For unauthenticated MCPs, connects on-demand to fetch tools.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    integration = get_integration_by_id(integration_id)
    if not integration or not integration.mcp_config:
        raise HTTPException(status_code=404, detail="Integration not found")

    token_store = MCPTokenStore(user_id=str(user_id))

    # For auth-required MCPs, try cached tools first
    if integration.mcp_config.requires_auth:
        # Check if connected
        is_connected = await token_store.is_connected(integration_id)
        if not is_connected:
            return MCPToolsResponse(tools=[], connected=False)

        # Return cached tools if available
        cached = await token_store.get_cached_tools(integration_id)
        if cached:
            return MCPToolsResponse(
                tools=[
                    MCPToolInfo(name=t["name"], description=t.get("description", ""))
                    for t in cached
                ],
                connected=True,
            )

        # Fallback: try to connect and cache tools
        # client.connect() handles caching with full args_schema
        client = get_mcp_client(user_id=str(user_id))
        try:
            tools = await client.connect(integration_id)
            if tools:
                return MCPToolsResponse(
                    tools=[
                        MCPToolInfo(name=t.name, description=t.description)
                        for t in tools
                    ],
                    connected=True,
                )
        except Exception as e:
            logger.warning(f"Failed to fetch tools for {integration_id}: {e}")

        return MCPToolsResponse(tools=[], connected=True)

    # For unauthenticated MCPs, connect on-demand
    client = get_mcp_client(user_id=str(user_id))
    if not client.is_connected(integration_id):
        try:
            await client.connect(integration_id)
        except Exception:
            return MCPToolsResponse(tools=[], connected=False)

    tools = await client.get_tools(integration_id)
    return MCPToolsResponse(
        tools=[MCPToolInfo(name=t.name, description=t.description) for t in tools],
        connected=True,
    )


@router.get("/status", response_model=MCPStatusResponse)
async def get_mcp_status(
    user: dict = Depends(get_current_user),
) -> MCPStatusResponse:
    """Get status of all MCP integrations for user."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    token_store = MCPTokenStore(user_id=str(user_id))

    mcp_integrations = [
        i for i in OAUTH_INTEGRATIONS if i.managed_by == "mcp" and i.mcp_config
    ]

    statuses = []
    for integration in mcp_integrations:
        # Unauthenticated MCPs are always connected
        if not integration.mcp_config.requires_auth:
            is_connected = True
        else:
            is_connected = await token_store.is_connected(integration.id)
        statuses.append(
            MCPIntegrationStatus(
                integrationId=integration.id,
                connected=is_connected,
                status="connected" if is_connected else "disconnected",
            )
        )

    return MCPStatusResponse(integrations=statuses)


async def _invalidate_status_cache(user_id: str) -> None:
    """Invalidate OAuth status cache for parity with Composio."""
    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"Invalidated MCP status cache for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate status cache: {e}")
