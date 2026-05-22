"""MCP proxy schemas."""

from app.schemas.mcp.requests import (
    MCPProxyPromptsListRequest,
    MCPProxyResourceReadRequest,
    MCPProxyResourcesListRequest,
    MCPProxyResourceTemplatesListRequest,
    MCPProxyToolCallRequest,
)
from app.schemas.mcp.responses import (
    MCPProxyPromptsListResponse,
    MCPProxyResourceReadResponse,
    MCPProxyResourcesListResponse,
    MCPProxyResourceTemplatesListResponse,
    MCPProxyToolCallResponse,
)

__all__ = [
    "MCPProxyToolCallRequest",
    "MCPProxyResourcesListRequest",
    "MCPProxyResourceTemplatesListRequest",
    "MCPProxyResourceReadRequest",
    "MCPProxyPromptsListRequest",
    "MCPProxyToolCallResponse",
    "MCPProxyResourcesListResponse",
    "MCPProxyResourceTemplatesListResponse",
    "MCPProxyResourceReadResponse",
    "MCPProxyPromptsListResponse",
]
