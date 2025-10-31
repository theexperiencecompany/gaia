"""
MCP Server Management API - MongoDB + mcp-use + OAuth

REST endpoints for managing MCP server configurations with OAuth support.
"""

from typing import Any, Dict, List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import common_logger as logger
from app.config.mcp_registry import (
    MCPServerTemplate,
    get_mcp_template_by_id,
    get_mcp_templates,
    get_mcp_templates_by_category,
)
from app.services.mcp import get_mcp_service
from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/templates", response_model=List[MCPServerTemplate])
async def list_mcp_templates(category: str | None = None):
    """List pre-configured MCP server templates."""
    try:
        if category:
            templates = get_mcp_templates_by_category(category)
        else:
            templates = get_mcp_templates()

        logger.info(f"Retrieved {len(templates)} MCP server templates")
        return templates

    except Exception as e:
        logger.error(f"Failed to retrieve MCP templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP templates",
        )


@router.get("/templates/{template_id}", response_model=MCPServerTemplate)
async def get_mcp_template(template_id: str):
    """Get a specific MCP server template by ID."""
    try:
        template = get_mcp_template_by_id(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template '{template_id}' not found",
            )

        return template

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve MCP template '{template_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP template",
        )


@router.get("/servers")
async def list_mcp_servers(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """List all MCP servers for the current user."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        servers = await mcp_service.get_user_servers(str(user_id))

        return {"servers": servers, "total": len(servers)}

    except Exception as e:
        logger.error(f"Failed to list MCP servers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP servers",
        )


@router.post("/servers", status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    request: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Create a new MCP server configuration.

    Request body:
    {
        "server_name": "github",
        "mcp_config": {"url": "...", "auth": {...}},
        "display_name": "GitHub",
        "description": "GitHub MCP Server",
        "oauth_integration_id": "github"
    }
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    if "server_name" not in request or "mcp_config" not in request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="server_name and mcp_config are required",
        )

    try:
        mcp_service = get_mcp_service()
        server = await mcp_service.create_server(
            user_id=str(user_id),
            server_name=request["server_name"],
            mcp_config=request["mcp_config"],
            display_name=request.get("display_name", request["server_name"]),
            description=request.get("description", ""),
            oauth_integration_id=request.get("oauth_integration_id"),
        )

        logger.info(f"Created MCP server '{server['server_name']}' for user {user_id}")
        return server

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create MCP server: {str(e)}",
        )


@router.get("/servers/{server_name}")
async def get_mcp_server(
    server_name: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get details of a specific MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        servers = await mcp_service.get_user_servers(str(user_id))

        server = next((s for s in servers if s["server_name"] == server_name), None)
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server '{server_name}' not found",
            )

        return server

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get MCP server {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP server",
        )


@router.put("/servers/{server_name}")
async def update_mcp_server(
    server_name: str,
    updates: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update an MCP server configuration."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        server = await mcp_service.update_server(str(user_id), server_name, updates)

        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server '{server_name}' not found",
            )

        logger.info(f"Updated MCP server {server_name} for user {user_id}")
        return server

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update MCP server {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update MCP server: {str(e)}",
        )


@router.delete("/servers/{server_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_name: str,
    user: dict = Depends(get_current_user),
):
    """Delete an MCP server configuration."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        success = await mcp_service.delete_server(str(user_id), server_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server '{server_name}' not found",
            )

        logger.info(f"Deleted MCP server {server_name} for user {user_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete MCP server {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete MCP server: {str(e)}",
        )


@router.get("/servers/{server_name}/status")
async def get_mcp_server_status(
    server_name: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get connection status and available tools for an MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        status_response = await mcp_service.get_server_status(str(user_id), server_name)

        if not status_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server '{server_name}' not found",
            )

        return status_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get server status for {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server status: {str(e)}",
        )


@router.get("/oauth/{server_name}/authorize")
async def mcp_oauth_authorize(
    server_name: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Initiate OAuth flow for an MCP server.

    Uses mcp-use library's OAuth discovery and DCR flow.
    Returns authorization URL for frontend to redirect user.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        auth_url = await mcp_service.initiate_oauth(
            user_id=str(user_id),
            server_name=server_name,
        )

        logger.info(f"Initiated OAuth for {server_name}, user {user_id}")
        return {"authorization_url": auth_url}

    except ValueError as e:
        logger.error(f"Invalid OAuth request for {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to initiate OAuth for {server_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate OAuth: {str(e)}",
        )


@router.get("/oauth/{server_name}/callback")
async def mcp_oauth_callback(
    server_name: str,
    code: str,
    state: str | None = None,
    user: dict = Depends(get_current_user),
) -> RedirectResponse:
    """
    Handle OAuth callback from MCP server.

    mcp-use handles token exchange and storage automatically.
    Redirects to frontend with success/error status.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        success = await mcp_service.complete_oauth(
            user_id=str(user_id),
            server_name=server_name,
            code=code,
            state=state,
        )

        if not success:
            logger.error(f"OAuth callback failed for {server_name}")
            return RedirectResponse(
                url=f"/settings/integrations?mcp_oauth=failed&server={server_name}"
            )

        logger.info(f"Completed OAuth for {server_name}, user {user_id}")
        return RedirectResponse(
            url=f"/settings/integrations?mcp_oauth=success&server={server_name}"
        )

    except Exception as e:
        logger.error(f"Failed to complete OAuth for {server_name}: {e}")
        return RedirectResponse(
            url=f"/settings/integrations?mcp_oauth=error&server={server_name}"
        )
