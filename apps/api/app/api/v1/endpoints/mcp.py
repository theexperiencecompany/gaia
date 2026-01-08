"""
MCP Integration API Routes.

Handles MCP OAuth callbacks and connection testing.
Connection/disconnection is handled by the unified /integrations endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import (
    get_api_base_url,
    get_frontend_url,
    invalidate_mcp_status_cache,
)
from app.services.integration_resolver import IntegrationResolver
from app.services.integration_service import update_user_integration_status
from app.services.mcp.mcp_client import get_mcp_client

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

    # Get server URL using IntegrationResolver
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        raise HTTPException(status_code=404, detail="Integration not found")

    server_url = resolved.server_url

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
