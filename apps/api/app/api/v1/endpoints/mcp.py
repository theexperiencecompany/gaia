"""
MCP Integration API Routes.

Handles MCP OAuth callbacks and tool discovery.
Connection/disconnection is handled by the unified /integrations endpoints.
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
    MCPIntegrationStatus,
    MCPStatusResponse,
    MCPToolInfo,
    MCPToolsResponse,
)
from app.services.integration_service import (
    check_user_has_integration,
    update_user_integration_status,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_token_store import MCPTokenStore

router = APIRouter()


@router.post("/test/{integration_id}")
async def test_mcp_connection(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Test connection to an MCP server.

    Probes the server and returns auth requirements.
    Can be used to retry failed connections.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    client = get_mcp_client(user_id=str(user_id))

    # Get server URL from integration config
    integration = get_integration_by_id(integration_id)
    server_url = None

    if integration and integration.mcp_config:
        server_url = integration.mcp_config.server_url
    else:
        # Try custom integration from MongoDB
        from app.db.mongodb.collections import integrations_collection

        custom_doc = await integrations_collection.find_one(
            {"integration_id": integration_id}
        )
        if custom_doc and custom_doc.get("mcp_config"):
            server_url = custom_doc["mcp_config"].get("server_url")

    if not server_url:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Probe the server
    probe_result = await client.probe_connection(server_url)

    if probe_result.get("error"):
        return JSONResponse(
            content={
                "status": "failed",
                "error": probe_result["error"],
            }
        )

    if not probe_result.get("requires_auth"):
        # Try to connect
        try:
            tools = await client.connect(integration_id)
            await update_user_integration_status(
                str(user_id), integration_id, "connected"
            )
            await invalidate_mcp_status_cache(str(user_id))
            return JSONResponse(
                content={
                    "status": "connected",
                    "tools_count": len(tools) if tools else 0,
                }
            )
        except Exception as e:
            return JSONResponse(
                content={
                    "status": "failed",
                    "error": str(e),
                }
            )

    # OAuth required
    auth_url = await client.build_oauth_auth_url(
        integration_id=integration_id,
        redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
        redirect_path="/integrations",
    )
    return JSONResponse(
        content={
            "status": "requires_oauth",
            "oauth_url": auth_url,
        }
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
