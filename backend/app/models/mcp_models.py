"""
MCP (Model Context Protocol) Server Models

Models for managing MCP server configurations, authentication, and state.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from app.db.postgresql import Base
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class MCPServerType(str, Enum):
    """Type of MCP server connection."""

    STDIO = "stdio"  # Local process via stdin/stdout
    HTTP = "http"  # HTTP/HTTPS connection
    SSE = "sse"  # Server-Sent Events


class MCPAuthType(str, Enum):
    """Authentication type for MCP servers."""

    NONE = "none"  # No authentication
    BEARER = "bearer"  # Bearer token
    OAUTH2 = "oauth2"  # OAuth 2.0
    BASIC = "basic"  # Basic auth
    DIGEST = "digest"  # Digest auth
    CUSTOM = "custom"  # Custom auth headers


class MCPAuthConfig(BaseModel):
    """Authentication configuration for MCP servers."""

    auth_type: MCPAuthType = MCPAuthType.NONE
    bearer_token: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_auth_url: Optional[str] = None
    oauth_token_url: Optional[str] = None
    oauth_scopes: Optional[List[str]] = None
    basic_username: Optional[str] = None
    basic_password: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None


class MCPStdioConfig(BaseModel):
    """Configuration for STDIO-based MCP servers."""

    command: str = Field(..., description="Command to execute")
    args: Optional[List[str]] = Field(default=None, description="Command arguments")
    env: Optional[Dict[str, str]] = Field(
        default=None, description="Environment variables"
    )
    cwd: Optional[str] = Field(default=None, description="Working directory")


class MCPHttpConfig(BaseModel):
    """Configuration for HTTP/SSE-based MCP servers."""

    url: str = Field(..., description="Server URL")
    headers: Optional[Dict[str, str]] = Field(
        default=None, description="Custom HTTP headers"
    )
    timeout: int = Field(default=30, description="Request timeout in seconds")


class MCPSandboxConfig(BaseModel):
    """Configuration for sandboxed MCP server execution."""

    enabled: bool = False
    api_key: Optional[str] = None
    template_id: str = "base"
    supergateway_command: str = "npx -y supergateway"


class MCPServerConfig(BaseModel):
    """Complete configuration for an MCP server."""

    id: Optional[str] = None
    name: str = Field(..., description="Display name for the server")
    description: str = Field(..., description="Description of server capabilities")
    server_type: MCPServerType = Field(..., description="Type of server connection")
    enabled: bool = Field(default=True, description="Whether server is active")
    stdio_config: Optional[MCPStdioConfig] = None
    http_config: Optional[MCPHttpConfig] = None
    auth_config: MCPAuthConfig = Field(
        default_factory=lambda: MCPAuthConfig(auth_type=MCPAuthType.NONE)
    )
    sandbox_config: Optional[MCPSandboxConfig] = None
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata"
    )

    def to_mcp_use_config(self) -> Dict[str, Any]:
        """Convert to mcp-use library configuration format."""
        config: Dict[str, Any] = {}

        if self.server_type == MCPServerType.STDIO and self.stdio_config:
            config["command"] = self.stdio_config.command
            if self.stdio_config.args:
                config["args"] = self.stdio_config.args
            if self.stdio_config.env:
                config["env"] = self.stdio_config.env

        elif self.server_type in [MCPServerType.HTTP, MCPServerType.SSE]:
            if self.http_config:
                config["url"] = self.http_config.url
                if self.http_config.headers:
                    config["headers"] = self.http_config.headers

            # Add authentication
            if self.auth_config.auth_type == MCPAuthType.BEARER:
                config["auth"] = self.auth_config.bearer_token
            elif self.auth_config.auth_type == MCPAuthType.OAUTH2:
                config["auth"] = {
                    "client_id": self.auth_config.oauth_client_id,
                    "client_secret": self.auth_config.oauth_client_secret,
                }
            elif self.auth_config.auth_type == MCPAuthType.CUSTOM:
                if self.auth_config.custom_headers:
                    config.setdefault("headers", {}).update(
                        self.auth_config.custom_headers
                    )

        return config


class MCPServer(Base):
    """SQLAlchemy model for MCP server configurations."""

    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    server_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="JSON serialized server configuration (without sensitive data)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class MCPCredential(Base):
    """SQLAlchemy model for MCP server credentials (stored securely in PostgreSQL)."""

    __tablename__ = "mcp_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    server_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Credentials (encrypted at rest by PostgreSQL)
    bearer_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    basic_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basic_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_headers: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="JSON serialized custom headers"
    )

    # Token metadata
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Space-separated OAuth scopes"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class MCPServerCreateRequest(BaseModel):
    """Request model for creating a new MCP server."""

    name: str
    description: str
    server_type: MCPServerType
    enabled: bool = True
    stdio_config: Optional[MCPStdioConfig] = None
    http_config: Optional[MCPHttpConfig] = None
    auth_config: Optional[MCPAuthConfig] = None
    sandbox_config: Optional[MCPSandboxConfig] = None
    metadata: Optional[Dict[str, Any]] = None


class MCPServerUpdateRequest(BaseModel):
    """Request model for updating an MCP server."""

    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    stdio_config: Optional[MCPStdioConfig] = None
    http_config: Optional[MCPHttpConfig] = None
    auth_config: Optional[MCPAuthConfig] = None
    sandbox_config: Optional[MCPSandboxConfig] = None
    metadata: Optional[Dict[str, Any]] = None


class MCPServerResponse(BaseModel):
    """Response model for MCP server."""

    id: int
    name: str
    description: str
    server_type: MCPServerType
    enabled: bool
    config: MCPServerConfig
    created_at: datetime
    updated_at: datetime


class MCPServerListResponse(BaseModel):
    """Response model for listing MCP servers."""

    servers: List[MCPServerResponse]
    total: int


class MCPToolInfo(BaseModel):
    """Information about a tool from an MCP server."""

    name: str
    description: str
    server_name: str
    parameters: Optional[Dict[str, Any]] = None


class MCPServerStatusResponse(BaseModel):
    """Status response for an MCP server connection."""

    server_id: int
    name: str
    connected: bool
    tool_count: int
    tools: List[MCPToolInfo]
    error: Optional[str] = None
