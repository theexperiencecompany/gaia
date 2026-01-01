"""
MCP API Models.

Pydantic models for MCP API request/response schemas.
"""

from typing import Optional

from pydantic import BaseModel


class MCPConnectRequest(BaseModel):
    """Request body for MCP connection."""

    bearer_token: Optional[str] = None


class MCPConnectResponse(BaseModel):
    """Response for MCP connection."""

    status: str
    integration_id: str
    tools_count: int
    redirect_url: Optional[str] = None
    message: Optional[str] = None


class MCPToolInfo(BaseModel):
    """Individual tool information."""

    name: str
    description: Optional[str] = None


class MCPToolsResponse(BaseModel):
    """Response for tools endpoint."""

    tools: list[MCPToolInfo]
    connected: bool


class MCPIntegrationStatus(BaseModel):
    """Status of a single MCP integration."""

    integrationId: str
    connected: bool
    status: str


class MCPStatusResponse(BaseModel):
    """Response for status endpoint."""

    integrations: list[MCPIntegrationStatus]
