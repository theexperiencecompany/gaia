"""
MCP proxy endpoints for MCP Apps iframe tool call proxying.
"""

from __future__ import annotations

from shared.py.wide_events import log

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
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_client import get_mcp_client
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter()


async def _resolve_server_url(integration_id: str, user_id: str) -> str:
    """Resolve an integration_id to its MCP server URL, server-side only.

    Never honour a client-supplied ``server_url`` — that would let any
    authenticated user point the proxy at internal services, metadata
    endpoints, or RFC 1918 addresses (SSRF). The lookup is also scoped
    to the caller's ``user_id`` so custom integrations belonging to
    another tenant cannot be reached by guessing their integration_id.
    """
    resolved = await IntegrationResolver.resolve(integration_id, user_id=user_id)
    if not resolved or not resolved.mcp_config or not resolved.mcp_config.server_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found or has no MCP server configured",
        )
    return resolved.mcp_config.server_url


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
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_tool_call",
        tool_name=request.tool_name,
        integration_id=request.integration_id,
    )

    server_url = await _resolve_server_url(request.integration_id, str(user_id))

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.call_tool_on_server(
            server_url=server_url,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        is_error = result.get("is_error") or result.get("isError") or False
        log.set(outcome="success", is_error=is_error)
        return MCPProxyToolCallResponse(
            content=result.get("content", []),
            is_error=is_error,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"MCP proxy tool call failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tool call failed",
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
    user: dict = Depends(get_current_user),
) -> MCPProxyResourcesListResponse:
    """Proxy a resources/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_resources_list",
        integration_id=request.integration_id,
    )

    server_url = await _resolve_server_url(request.integration_id, str(user_id))

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resources_on_server(
            server_url=server_url,
            cursor=request.cursor,
        )
        log.set(outcome="success", result_count=len(result.get("resources", [])))
        return MCPProxyResourcesListResponse(
            resources=result.get("resources", []),
            next_cursor=result.get("next_cursor") or result.get("nextCursor"),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"MCP proxy resources/list failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="resources/list failed",
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
    user: dict = Depends(get_current_user),
) -> MCPProxyResourceTemplatesListResponse:
    """Proxy a resources/templates/list request from an MCP App iframe."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_resource_templates_list",
        integration_id=request.integration_id,
    )

    server_url = await _resolve_server_url(request.integration_id, str(user_id))

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_resource_templates_on_server(
            server_url=server_url,
            cursor=request.cursor,
        )
        log.set(
            outcome="success",
            result_count=len(
                result.get("resource_templates")
                or result.get("resourceTemplates")
                or []
            ),
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
        log.error(f"MCP proxy resources/templates/list failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="resources/templates/list failed",
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
    user: dict = Depends(get_current_user),
) -> MCPProxyResourceReadResponse:
    """Proxy a resources/read request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_resource_read",
        resource_uri=request.uri,
        integration_id=request.integration_id,
    )

    server_url = await _resolve_server_url(request.integration_id, str(user_id))

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.read_resource_on_server(
            server_url=server_url,
            uri=request.uri,
        )
        log.set(outcome="success", result_count=len(result.get("contents", [])))
        return MCPProxyResourceReadResponse(
            contents=result.get("contents", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"MCP proxy resources/read failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="resources/read failed",
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
    user: dict = Depends(get_current_user),
) -> MCPProxyPromptsListResponse:
    """Proxy a prompts/list request from an MCP App iframe to the MCP server."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="mcp_proxy_prompts_list",
        integration_id=request.integration_id,
    )

    server_url = await _resolve_server_url(request.integration_id, str(user_id))

    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        result = await mcp_client.list_prompts_on_server(
            server_url=server_url,
            cursor=request.cursor,
        )
        log.set(outcome="success", result_count=len(result.get("prompts", [])))
        return MCPProxyPromptsListResponse(
            prompts=result.get("prompts", []),
            next_cursor=result.get("next_cursor") or result.get("nextCursor"),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"MCP proxy prompts/list failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="prompts/list failed",
        ) from e
