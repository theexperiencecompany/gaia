"""
MCP API Models.

Pydantic models for MCP API request/response schemas.
"""

from typing import Optional

from pydantic import BaseModel


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
