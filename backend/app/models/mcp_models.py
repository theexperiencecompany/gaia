"""
MCP (Model Context Protocol) Server Models - MongoDB + mcp-use

Minimal models for MCP server configurations.
Uses MongoDB for storage, mcp-use handles OAuth and tokens.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MCPServerCreateRequest(BaseModel):
    """Request model for creating MCP server - MongoDB format."""

    server_name: str = Field(
        ..., description="Unique server identifier (e.g., 'github', 'linear')"
    )
    display_name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(
        None, description="Description of server capabilities"
    )
    mcp_config: Dict[str, Any] = Field(
        ..., description="Raw mcp-use configuration dict"
    )
    oauth_integration_id: Optional[str] = Field(
        None, description="OAuth integration ID if using OAuth"
    )
    enabled: bool = Field(True, description="Whether server is active")


class MCPServerUpdateRequest(BaseModel):
    """Request model for updating MCP server."""

    display_name: Optional[str] = None
    description: Optional[str] = None
    mcp_config: Optional[Dict[str, Any]] = None
    oauth_integration_id: Optional[str] = None
    enabled: Optional[bool] = None


class MCPServerResponse(BaseModel):
    """Response model for MCP server from MongoDB."""

    id: str = Field(..., alias="_id", description="MongoDB document ID")
    user_id: str
    server_name: str
    display_name: str
    description: Optional[str] = None
    mcp_config: Dict[str, Any]
    oauth_integration_id: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class MCPServerListResponse(BaseModel):
    """Response model for listing MCP servers."""

    servers: list[Dict[str, Any]]
    total: int


class MCPServerStatusResponse(BaseModel):
    """Status response for an MCP server connection."""

    server_name: str
    connected: bool
    tool_count: int
    tools: list[Dict[str, Any]]
    error: Optional[str] = None
