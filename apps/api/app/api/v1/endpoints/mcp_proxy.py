"""
MCP proxy endpoints for MCP Apps iframe tool call proxying.
"""

from __future__ import annotations

import logging
from typing import Any

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.services.mcp.mcp_client import get_mcp_client
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class MCPProxyToolCallRequest(BaseModel):
    server_url: str
    tool_name: str
    arguments: dict[str, Any] = {}


class MCPProxyToolCallResponse(BaseModel):
    content: list[dict[str, Any]]
    is_error: bool = False


@router.post(
    "/proxy/tool-call",
    response_model=MCPProxyToolCallResponse,
    summary="Proxy a tool call from an MCP App iframe to the MCP server",
)
async def proxy_mcp_tool_call(
    request: MCPProxyToolCallRequest,
    user: dict = Depends(get_current_user),
) -> MCPProxyToolCallResponse:
    """
    Proxy a tool call from an MCP App iframe to the MCP server.
    The iframe cannot call the MCP server directly due to sandboxing.
    """
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
            is_error=result.get("isError", False),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP proxy tool call failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool call failed: {str(e)}",
        )
