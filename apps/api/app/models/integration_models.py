"""
Integration Models for MCP Marketplace.

This module defines Pydantic models for:
- Integration catalog (platform + custom MCPs)
- User integration connections
- API request/response schemas
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class IntegrationTool(BaseModel):
    """Tool metadata for frontend display (not used by LLM)."""

    name: str
    description: Optional[str] = None


class MCPConfigDoc(BaseModel):
    """MCP configuration stored in MongoDB for custom integrations."""

    server_url: str
    requires_auth: bool = False
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    transport: Optional[str] = None
    oauth_scopes: Optional[List[str]] = None


class ComposioConfigDoc(BaseModel):
    """Composio configuration stored in MongoDB."""

    auth_config_id: str
    toolkit: str


class Integration(BaseModel):
    """
    Integration document model for MongoDB 'integrations' collection.

    Platform integrations from OAUTH_INTEGRATIONS (code) are hydrated at runtime.
    Custom integrations created by users are stored here.
    """

    integration_id: str = Field(
        ..., description="Unique identifier for the integration"
    )
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="User-facing description")
    category: str = Field(
        ..., description="e.g., productivity, communication, developer"
    )

    # Management and source
    managed_by: Literal["self", "composio", "mcp", "internal"] = Field(
        ..., description="Which system manages the integration"
    )
    source: Literal["platform", "custom"] = Field(
        "custom", description="Platform (from code) or custom (user-created)"
    )

    # Visibility and ownership
    is_public: bool = Field(False, description="Visible in public marketplace")
    created_by: Optional[str] = Field(
        None, description="User ID for custom integrations"
    )

    # Configuration (one of these based on managed_by)
    mcp_config: Optional[MCPConfigDoc] = None
    composio_config: Optional[ComposioConfigDoc] = None

    # Frontend display metadata
    tools: List[IntegrationTool] = Field(
        default_factory=list, description="Tool list for frontend display only"
    )
    icon_url: Optional[str] = Field(
        None, description="Favicon URL fetched from MCP server subdomain"
    )
    display_priority: int = Field(0, description="Higher priority shows first")
    is_featured: bool = Field(False, description="Show in featured section")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class UserIntegration(BaseModel):
    """
    User integration document model for MongoDB 'user_integrations' collection.

    Tracks which integrations a user has added to their workspace
    and their connection status.
    """

    user_id: str = Field(..., description="User's MongoDB ObjectId as string")
    integration_id: str = Field(..., description="Reference to integration")
    status: Literal["created", "connected"] = Field(
        "created",
        description="'created' = added but not authenticated, 'connected' = ready to use",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    connected_at: Optional[datetime] = Field(
        None, description="When OAuth/auth was completed"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class AddUserIntegrationRequest(BaseModel):
    """Request to add an integration to user's workspace."""

    integration_id: str = Field(..., description="ID of integration to add")


class CreateCustomIntegrationRequest(BaseModel):
    """Request to create a custom MCP integration."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    category: str = Field(default="custom")
    server_url: str = Field(..., description="MCP server URL")
    requires_auth: bool = Field(False)
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = Field(None)
    is_public: bool = Field(False, description="Make visible in marketplace")


class UpdateCustomIntegrationRequest(BaseModel):
    """Request to update a custom integration (partial update)."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    server_url: Optional[str] = None
    requires_auth: Optional[bool] = None
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    is_public: Optional[bool] = None


class IntegrationResponse(BaseModel):
    """Integration details for API responses."""

    integration_id: str
    name: str
    description: str
    category: str
    managed_by: Literal["self", "composio", "mcp", "internal"]
    source: Literal["platform", "custom"]
    is_featured: bool
    display_priority: int

    # Config details (optional, depends on managed_by)
    requires_auth: bool = False
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None

    # Tool metadata for frontend display
    tools: List[IntegrationTool] = Field(default_factory=list)

    # Icon URL for custom integrations (favicon from MCP server)
    icon_url: Optional[str] = None

    # Custom integration fields
    is_public: Optional[bool] = None
    created_by: Optional[str] = None

    @classmethod
    def from_integration(cls, integration: Integration) -> "IntegrationResponse":
        """Convert Integration model to response."""
        requires_auth = False
        auth_type = None

        if integration.mcp_config:
            requires_auth = integration.mcp_config.requires_auth
            auth_type = integration.mcp_config.auth_type or (
                "oauth" if requires_auth else "none"
            )

        return cls(
            integration_id=integration.integration_id,
            name=integration.name,
            description=integration.description,
            category=integration.category,
            managed_by=integration.managed_by,
            source=integration.source,
            is_featured=integration.is_featured,
            display_priority=integration.display_priority,
            requires_auth=requires_auth,
            auth_type=auth_type,
            tools=integration.tools,
            icon_url=integration.icon_url,
            is_public=integration.is_public,
            created_by=integration.created_by,
        )

    @classmethod
    def from_oauth_integration(cls, oauth_int) -> "IntegrationResponse":
        """Convert OAuthIntegration from config to response."""
        requires_auth = False
        auth_type = None

        if oauth_int.mcp_config:
            requires_auth = oauth_int.mcp_config.requires_auth
            auth_type = "oauth" if requires_auth else "none"
        elif oauth_int.composio_config:
            requires_auth = True
            auth_type = "oauth"

        return cls(
            integration_id=oauth_int.id,
            name=oauth_int.name,
            description=oauth_int.description,
            category=oauth_int.category,
            managed_by=oauth_int.managed_by,
            source="platform",
            is_featured=oauth_int.is_featured,
            display_priority=oauth_int.display_priority,
            requires_auth=requires_auth,
            auth_type=auth_type,
            tools=[],  # Platform tools are loaded live, not stored
        )


class UserIntegrationResponse(BaseModel):
    """User integration with hydrated integration details."""

    integration_id: str
    status: Literal["created", "connected"]
    created_at: datetime
    connected_at: Optional[datetime] = None

    # Hydrated integration details
    integration: IntegrationResponse


class MarketplaceResponse(BaseModel):
    """Response for marketplace listing."""

    featured: List[IntegrationResponse] = Field(default_factory=list)
    integrations: List[IntegrationResponse] = Field(default_factory=list)
    total: int = 0


class UserIntegrationsListResponse(BaseModel):
    """Response for user's integrations listing."""

    integrations: List[UserIntegrationResponse] = Field(default_factory=list)
    total: int = 0
