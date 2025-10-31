"""
MCP Server Management API

REST endpoints for managing MCP server configurations.
"""

from typing import List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import common_logger as logger
from app.config.mcp_registry import (
    MCPServerTemplate,
    get_mcp_template_by_id,
    get_mcp_templates,
    get_mcp_templates_by_category,
)
from app.models.mcp_models import (
    MCPServerCreateRequest,
    MCPServerListResponse,
    MCPServerResponse,
    MCPServerStatusResponse,
    MCPServerUpdateRequest,
)
from app.services.mcp import get_mcp_service
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/templates", response_model=List[MCPServerTemplate])
async def list_mcp_templates(category: str | None = None):
    """
    List pre-configured MCP server templates.

    Args:
        category: Optional category filter (development, productivity, monitoring, data)

    Returns:
        List of MCP server templates
    """
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
    """
    Get a specific MCP server template by ID.

    Args:
        template_id: Template identifier

    Returns:
        MCP server template
    """
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


@router.get("/servers", response_model=MCPServerListResponse)
async def list_mcp_servers(
    user: dict = Depends(get_current_user),
):
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

        responses = [
            MCPServerResponse(
                id=server.id,
                name=server.name,
                description=server.description or "",
                server_type=server.server_type,  # type: ignore
                enabled=server.enabled,
                config=server.config,  # type: ignore
                created_at=server.created_at,
                updated_at=server.updated_at,
            )
            for server in servers
        ]

        return MCPServerListResponse(servers=responses, total=len(responses))

    except Exception as e:
        logger.error(f"Failed to list MCP servers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP servers",
        )


@router.post(
    "/servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED
)
async def create_mcp_server(
    request: MCPServerCreateRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new MCP server configuration."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        server = await mcp_service.create_server(str(user_id), request)

        logger.info(f"Created MCP server '{server.name}' for user {user_id}")
        return server

    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create MCP server: {str(e)}",
        )


@router.get("/servers/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: int,
    user: dict = Depends(get_current_user),
):
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

        server = next((s for s in servers if s.id == server_id), None)
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

        return MCPServerResponse(
            id=server.id,
            name=server.name,
            description=server.description or "",
            server_type=server.server_type,  # type: ignore
            enabled=server.enabled,
            config=server.config,  # type: ignore
            created_at=server.created_at,
            updated_at=server.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get MCP server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP server",
        )


@router.put("/servers/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: int,
    request: MCPServerUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update an MCP server configuration."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        server = await mcp_service.update_server(str(user_id), server_id, request)

        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

        logger.info(f"Updated MCP server {server_id} for user {user_id}")
        return server

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update MCP server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update MCP server: {str(e)}",
        )


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: int,
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
        success = await mcp_service.delete_server(str(user_id), server_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

        logger.info(f"Deleted MCP server {server_id} for user {user_id}")
        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete MCP server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP server",
        )


@router.get("/servers/{server_id}/status", response_model=MCPServerStatusResponse)
async def get_mcp_server_status(
    server_id: int,
    user: dict = Depends(get_current_user),
):
    """Get connection status and available tools for an MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        status_response = await mcp_service.get_server_status(str(user_id), server_id)

        if not status_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

        return status_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get status for MCP server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve MCP server status",
        )


@router.post("/servers/{server_id}/test")
async def test_mcp_server_connection(
    server_id: int,
    user: dict = Depends(get_current_user),
):
    """Test connection to an MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found",
        )

    try:
        mcp_service = get_mcp_service()
        status_response = await mcp_service.get_server_status(str(user_id), server_id)

        if not status_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

        return {
            "connected": status_response.connected,
            "tool_count": status_response.tool_count,
            "error": status_response.error,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test MCP server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test MCP server connection: {str(e)}",
        )
