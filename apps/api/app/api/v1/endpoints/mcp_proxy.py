"""
MCP proxy endpoints for MCP Apps iframe tool call proxying.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.models.user_models import AuthenticatedUser
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
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import McpContext, log

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
    user: AuthenticatedUser = Depends(get_current_user),
) -> MCPProxyToolCallResponse:
    """Proxy a tools/call request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_tool_call",
        mcp=McpContext(operation="call_tool", tool_name=request.tool_name),
    )

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.call_tool_on_server(
            server_url=request.server_url,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        log.set(outcome="success")
        log.set_ns("mcp", success=not result.isError)
        capture_context_event(
            AnalyticsEvents.TOOL_USED,
            {"tool_name": request.tool_name, "source": "mcp_app"},
        )
        return MCPProxyToolCallResponse(
            content=[block.model_dump() for block in result.content],
            is_error=result.isError,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.MCP} MCP proxy tool call failed",
            user_id=user_id,
            tool_name=request.tool_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool call failed: {e!s}",
        ) from e


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
    user: AuthenticatedUser = Depends(get_current_user),
) -> MCPProxyResourcesListResponse:
    """Proxy a resources/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(user={"id": user_id}, operation="mcp_proxy_resources_list")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resources_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        log.set(outcome="success")
        log.set(mcp=McpContext(success=True, result_count=len(result.resources)))
        return MCPProxyResourcesListResponse(
            resources=[r.model_dump(mode="json", by_alias=True) for r in result.resources],
            next_cursor=result.nextCursor,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.MCP} MCP proxy resources/list failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/list failed: {e!s}",
        ) from e


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
    user: AuthenticatedUser = Depends(get_current_user),
) -> MCPProxyResourceTemplatesListResponse:
    """Proxy a resources/templates/list request from an MCP App iframe."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(user={"id": user_id}, operation="mcp_proxy_resource_templates_list")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resource_templates_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        log.set(outcome="success")
        log.set(mcp=McpContext(success=True, result_count=len(result.resourceTemplates)))
        return MCPProxyResourceTemplatesListResponse(
            resource_templates=[
                t.model_dump(mode="json", by_alias=True) for t in result.resourceTemplates
            ],
            next_cursor=result.nextCursor,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.MCP} MCP proxy resources/templates/list failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/templates/list failed: {e!s}",
        ) from e


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
    user: AuthenticatedUser = Depends(get_current_user),
) -> MCPProxyResourceReadResponse:
    """Proxy a resources/read request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_resource_read",
        resource_uri=request.uri,
    )

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.read_resource_on_server(
            server_url=request.server_url,
            uri=request.uri,
        )
        log.set(outcome="success")
        log.set(mcp=McpContext(success=True, result_count=len(result.contents)))
        return MCPProxyResourceReadResponse(
            contents=[c.model_dump(mode="json", by_alias=True) for c in result.contents],
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.MCP} MCP proxy resources/read failed",
            user_id=user_id,
            resource_uri=request.uri,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"resources/read failed: {e!s}",
        ) from e


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
    user: AuthenticatedUser = Depends(get_current_user),
) -> MCPProxyPromptsListResponse:
    """Proxy a prompts/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(user={"id": user_id}, operation="mcp_proxy_prompts_list")

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_prompts_on_server(
            server_url=request.server_url,
            cursor=request.cursor,
        )
        log.set(outcome="success")
        log.set(mcp=McpContext(success=True, result_count=len(result.prompts)))
        return MCPProxyPromptsListResponse(
            prompts=[pr.model_dump(mode="json", by_alias=True) for pr in result.prompts],
            next_cursor=result.nextCursor,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.MCP} MCP proxy prompts/list failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"prompts/list failed: {e!s}",
        ) from e
