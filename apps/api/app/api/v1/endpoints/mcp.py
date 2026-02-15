"""
MCP Integration API Routes.

Handles MCP OAuth callbacks and connection testing.
Connection/disconnection is handled by the unified /integrations endpoints.
"""

from typing import Optional
from urllib.parse import quote

from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import (
    get_api_base_url,
    get_frontend_url,
    invalidate_mcp_status_cache,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_client import get_mcp_client
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

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

    client = await get_mcp_client(user_id=str(user_id))

    # Get server URL using IntegrationResolver
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        raise HTTPException(status_code=404, detail="Integration not found")

    server_url = resolved.mcp_config.server_url

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
            # Note: status update now handled in connect()
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

    # OAuth required - update MongoDB with discovered auth requirements
    auth_type = probe_result.get("auth_type", "oauth")
    await client.update_integration_auth_status(
        integration_id, requires_auth=True, auth_type=auth_type
    )

    try:
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
    except Exception as e:
        logger.error(f"OAuth URL build failed for {integration_id}: {e}")
        return JSONResponse(
            content={
                "status": "failed",
                "error": str(e),
            }
        )


@router.get("/oauth/callback")
async def mcp_oauth_callback(
    state: str = Query(...),
    code: Optional[str] = Query(None),  # Optional - may be missing if error
    error: Optional[str] = Query(None),  # OAuth error code
    error_description: Optional[str] = Query(None),  # OAuth error description
    user: dict = Depends(get_current_user),
):
    """Handle OAuth callback from MCP server.

    Handles both success (with code) and error responses from OAuth server.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    frontend_url = get_frontend_url()

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
        return RedirectResponse(
            url=f"{frontend_url}/integrations?status=failed&error=invalid_state"
        )

    # Handle OAuth error response from authorization server
    if error:
        logger.warning(
            f"OAuth error for {integration_id}: {error} - {error_description or 'no description'}"
        )
        # Map common OAuth errors to user-friendly codes
        error_code = error
        if error == "server_error":
            error_code = "oauth_server_error"
        elif error not in [
            "access_denied",
            "invalid_request",
            "unauthorized_client",
            "unsupported_response_type",
            "invalid_scope",
            "server_error",
            "temporarily_unavailable",
        ]:
            error_code = "authorization_failed"  # Generic fallback

        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={error_code}"
        )

    # Validate code is present (required for success case)
    if not code:
        logger.error(f"OAuth callback missing code for {integration_id}")
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error=missing_code"
        )

    client = await get_mcp_client(user_id=str(user_id))

    # Resolve integration name for the frontend toast
    resolved = await IntegrationResolver.resolve(integration_id)
    integration_name = resolved.name if resolved else integration_id

    try:
        tools = await client.handle_oauth_callback(
            integration_id=integration_id,
            code=code,
            state=state_token,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
        )

        # handle_oauth_callback() already calls connect() internally
        # and returns tools, so we don't need to call connect() again
        if tools:
            logger.info(
                f"Connected with {len(tools)} tools for {integration_id} after OAuth"
            )

            tool_registry = await get_tool_registry()
            await tool_registry.load_user_mcp_tools(str(user_id))
            logger.info(f"Indexed MCP tools from {integration_id} to ChromaDB")

            try:
                await delete_cache("api:get_available_tools:*")
                logger.info("Invalidated tools list cache after MCP connection")
            except Exception as cache_err:
                logger.warning(f"Failed to invalidate tools cache: {cache_err}")

        await invalidate_mcp_status_cache(str(user_id))

        # Subagent indexing handled in MCPClient._handle_custom_integration_connect

        frontend_url = get_frontend_url()

        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=connected&name={quote(integration_name)}"
        )

    except Exception as e:
        logger.error(f"OAuth callback failed for {integration_id}: {e}")
        frontend_url = get_frontend_url()
        # Sanitize error - use generic codes instead of raw exception messages
        error_code = "connection_failed"
        if "state" in str(e).lower():
            error_code = "invalid_state"
        elif "token" in str(e).lower():
            error_code = "token_exchange_failed"
        elif "discovery" in str(e).lower():
            error_code = "discovery_failed"
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={error_code}"
        )
