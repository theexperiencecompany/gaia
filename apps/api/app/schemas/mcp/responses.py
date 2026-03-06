"""MCP proxy response schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class MCPProxyToolCallResponse(BaseModel):
    """Response for a proxied tools/call."""

    content: list[dict[str, Any]]
    is_error: bool = False


class MCPProxyResourcesListResponse(BaseModel):
    """Response for a proxied resources/list."""

    resources: list[dict[str, Any]]
    next_cursor: Optional[str] = None


class MCPProxyResourceTemplatesListResponse(BaseModel):
    """Response for a proxied resources/templates/list."""

    resource_templates: list[dict[str, Any]]
    next_cursor: Optional[str] = None


class MCPProxyResourceReadResponse(BaseModel):
    """Response for a proxied resources/read."""

    contents: list[dict[str, Any]]


class MCPProxyPromptsListResponse(BaseModel):
    """Response for a proxied prompts/list."""

    prompts: list[dict[str, Any]]
    next_cursor: Optional[str] = None
