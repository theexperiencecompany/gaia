"""MCP proxy request schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class MCPProxyToolCallRequest(BaseModel):
    """Proxy a tools/call from an MCP App iframe."""

    server_url: str
    tool_name: str
    arguments: dict[str, Any] = {}


class MCPProxyResourcesListRequest(BaseModel):
    """Proxy a resources/list request from an MCP App iframe."""

    server_url: str
    cursor: Optional[str] = None


class MCPProxyResourceTemplatesListRequest(BaseModel):
    """Proxy a resources/templates/list request from an MCP App iframe."""

    server_url: str
    cursor: Optional[str] = None


class MCPProxyResourceReadRequest(BaseModel):
    """Proxy a resources/read request from an MCP App iframe."""

    server_url: str
    uri: str


class MCPProxyPromptsListRequest(BaseModel):
    """Proxy a prompts/list request from an MCP App iframe."""

    server_url: str
    cursor: Optional[str] = None
