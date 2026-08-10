"""MCP proxy request schemas."""

from __future__ import annotations

from pydantic import BaseModel


class MCPProxyToolCallRequest(BaseModel):  # type: ignore[explicit-any]
    """Proxy a tools/call from an MCP App iframe."""

    server_url: str
    tool_name: str
    arguments: dict[str, object] = {}


class MCPProxyResourcesListRequest(BaseModel):  # type: ignore[explicit-any]
    """Proxy a resources/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None


class MCPProxyResourceTemplatesListRequest(BaseModel):  # type: ignore[explicit-any]
    """Proxy a resources/templates/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None


class MCPProxyResourceReadRequest(BaseModel):  # type: ignore[explicit-any]
    """Proxy a resources/read request from an MCP App iframe."""

    server_url: str
    uri: str


class MCPProxyPromptsListRequest(BaseModel):  # type: ignore[explicit-any]
    """Proxy a prompts/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None
