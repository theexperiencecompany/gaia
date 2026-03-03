"""
MCP proxy endpoints for MCP Apps iframe tool call proxying.
"""

from __future__ import annotations

import logging

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.schemas.mcp import (
    MCPProxyPromptsListRequest,
    MCPProxyPromptsListResponse,
    MCPProxyResourceReadRequest,
    MCPProxyResourceReadResponse,
    MCPProxyResourcesListRequest,
    MCPProxyResourcesListResponse,
    MCPProxyResourceTemplatesListRequest,
    MCPProxyResourceTemplatesListResponse,
    MCPProxyToolCallRequest,
    MCPProxyToolCallResponse,
)
from app.services.mcp.mcp_client import get_mcp_client
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Tool call
# ---------------------------------------------------------------------------


@router.post(
    "/proxy/tool-call",
    response_model=MCPProxyToolCallResponse,
    summary="Proxy a tool call from an MCP App iframe to the MCP server",
)
async def proxy_mcp_tool_call(
    request: MCPProxyToolCallRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyToolCallResponse:
    """Proxy a tools/call request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.call_tool_on_server(
            server_url=request.server_url,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        return MCPProxyToolCallResponse(
            content=result.get("content", []),
            is_error=result.get("is_error") or result.get("isError") or False,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy tool call failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool call failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Resources list
# ---------------------------------------------------------------------------


@router.post(
    "/proxy/resources/list",
    response_model=MCPProxyResourcesListResponse,
    summary="Proxy a resources/list request from an MCP App iframe",
)
async def proxy_mcp_resources_list(
    request: MCPProxyResourcesListRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyResourcesListResponse:
    """Proxy a resources/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resources_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        return MCPProxyResourcesListResponse(
            resources=result.get("resources", []),
            next_cursor=result.get("next_cursor") or result.get("nextCursor"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy resources/list failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/list failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Resource templates list
# ---------------------------------------------------------------------------


@router.post(
    "/proxy/resources/templates/list",
    response_model=MCPProxyResourceTemplatesListResponse,
    summary="Proxy a resources/templates/list request from an MCP App iframe",
)
async def proxy_mcp_resource_templates_list(
    request: MCPProxyResourceTemplatesListRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyResourceTemplatesListResponse:
    """Proxy a resources/templates/list request from an MCP App iframe."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resource_templates_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        return MCPProxyResourceTemplatesListResponse(
            resource_templates=result.get("resource_templates")
            or result.get("resourceTemplates")
            or [],
            next_cursor=result.get("next_cursor") or result.get("nextCursor"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy resources/templates/list failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/templates/list failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Resource read
# ---------------------------------------------------------------------------


@router.post(
    "/proxy/resources/read",
    response_model=MCPProxyResourceReadResponse,
    summary="Proxy a resources/read request from an MCP App iframe",
)
async def proxy_mcp_resource_read(
    request: MCPProxyResourceReadRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyResourceReadResponse:
    """Proxy a resources/read request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.read_resource_on_server(
            server_url=request.server_url,
            uri=request.uri,
        )
        return MCPProxyResourceReadResponse(
            contents=result.get("contents", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy resources/read failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/read failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Prompts list
# ---------------------------------------------------------------------------


@router.post(
    "/proxy/prompts/list",
    response_model=MCPProxyPromptsListResponse,
    summary="Proxy a prompts/list request from an MCP App iframe",
)
async def proxy_mcp_prompts_list(
    request: MCPProxyPromptsListRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyPromptsListResponse:
    """Proxy a prompts/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_prompts_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        return MCPProxyPromptsListResponse(
            prompts=result.get("prompts", []),
            next_cursor=result.get("next_cursor") or result.get("nextCursor"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy prompts/list failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"prompts/list failed: {str(e)}",
        )
