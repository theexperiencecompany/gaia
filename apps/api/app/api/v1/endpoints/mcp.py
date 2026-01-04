"""
MCP Integration API Routes.

Handles MCP connection, OAuth callbacks, disconnection, and tool discovery.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import (
    get_api_base_url,
    get_frontend_url,
    invalidate_mcp_status_cache,
)
from app.models.mcp_models import (
    MCPConnectRequest,
    MCPConnectResponse,
    MCPIntegrationStatus,
    MCPStatusResponse,
    MCPToolInfo,
    MCPToolsResponse,
)
from app.services.integration_service import (
    check_user_has_integration,
    remove_user_integration,
    update_user_integration_status,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store

router = APIRouter()


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
        auth_url = await client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path=redirect_path,
        )
        return RedirectResponse(url=auth_url)

    except Exception as e:
        logger.error(f"OAuth initiation failed for {integration_id}: {e}")
        frontend_url = get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={str(e)}"
        )


@router.post("/connect/{integration_id}", response_model=MCPConnectResponse)
async def connect_mcp(
    integration_id: str,
    request: MCPConnectRequest,
    user: dict = Depends(get_current_user),
):
    """
    Connect to an MCP integration.

    For unauthenticated MCPs - creates user_integrations record and fetches tools.
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

    # Unauthenticated MCPs - create user_integrations record and fetch tools
    try:
        # Create/update user_integrations record
        await update_user_integration_status(str(user_id), integration_id, "connected")
        logger.info(f"Created user_integrations record for {integration_id}")

        # Connect to MCP server and fetch tools
        client = get_mcp_client(user_id=str(user_id))
        tools = await client.connect(integration_id)
        tools_count = len(tools) if tools else 0

        # Store tools globally for frontend visibility
        if tools:
            global_store = get_mcp_tools_store()
            tool_metadata = [
                {"name": t.name, "description": t.description or ""} for t in tools
            ]
            await global_store.store_tools(integration_id, tool_metadata)
            logger.info(f"Stored {tools_count} tools globally for {integration_id}")

        # Invalidate status cache
        await invalidate_mcp_status_cache(str(user_id))

        return MCPConnectResponse(
            status="connected",
            integration_id=integration_id,
            tools_count=tools_count,
            message=f"{integration.name} connected successfully",
        )
    except Exception as e:
        logger.error(f"Failed to connect {integration_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")


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
        frontend_url = get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}/integrations?status=failed&error=invalid_state"
        )

    client = get_mcp_client(user_id=str(user_id))

    try:
        await client.handle_oauth_callback(
            integration_id=integration_id,
            code=code,
            state=state_token,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
        )

        try:
            tools = await client.connect(integration_id)
            if tools:
                logger.info(
                    f"Connected and cached {len(tools)} tools for {integration_id} after OAuth"
                )

                tool_registry = await get_tool_registry()
                await tool_registry.load_user_mcp_tools(str(user_id))
                logger.info(f"Indexed MCP tools from {integration_id} to ChromaDB")

                try:
                    # Cache key is api:get_available_tools:<hash> (namespace="api")
                    await delete_cache("api:get_available_tools:*")
                    logger.info("Invalidated tools list cache after MCP connection")
                except Exception as cache_err:
                    logger.warning(f"Failed to invalidate tools cache: {cache_err}")
        except Exception as tool_err:
            logger.warning(f"Failed to cache tools for {integration_id}: {tool_err}")

        await invalidate_mcp_status_cache(str(user_id))

        # Update user_integrations status in MongoDB
        try:
            await update_user_integration_status(
                str(user_id), integration_id, "connected"
            )
            logger.info(f"Updated user_integrations status for {integration_id}")
        except Exception as status_err:
            logger.warning(f"Failed to update user_integrations: {status_err}")

        frontend_url = get_frontend_url()
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=connected"
        )

    except Exception as e:
        logger.error(f"OAuth callback failed for {integration_id}: {e}")
        frontend_url = get_frontend_url()
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

    integration = get_integration_by_id(integration_id)
    if not integration or not integration.mcp_config:
        raise HTTPException(status_code=404, detail="MCP integration not found")

    # For unauthenticated MCPs, just remove user_integrations record
    if not integration.mcp_config.requires_auth:
        removed = await remove_user_integration(str(user_id), integration_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail="Integration not found in your workspace"
            )
        await invalidate_mcp_status_cache(str(user_id))
        return JSONResponse(
            content={"status": "success", "message": f"Disconnected {integration_id}"}
        )

    # For authenticated MCPs, clear credentials
    client = get_mcp_client(user_id=str(user_id))
    await client.disconnect(integration_id)

    # Also remove from user_integrations
    await remove_user_integration(str(user_id), integration_id)

    await invalidate_mcp_status_cache(str(user_id))

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
        # Unauthenticated MCPs check user_integrations
        if not integration.mcp_config.requires_auth:
            is_connected = await check_user_has_integration(
                str(user_id), integration.id
            )
        else:
            # Authenticated MCPs check mcp_credentials
            is_connected = await token_store.is_connected(integration.id)
        statuses.append(
            MCPIntegrationStatus(
                integrationId=integration.id,
                connected=is_connected,
                status="connected" if is_connected else "disconnected",
            )
        )

    return MCPStatusResponse(integrations=statuses)
