"""
Integration Models for MCP Marketplace.

This module defines Pydantic models for:
- Integration catalog (platform + custom MCPs)
- User integration connections
- API request/response schemas
"""

from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.helpers.integration_helpers import generate_integration_slug
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import OAuthIntegration

# Type alias for auth_type
AuthType = Literal["none", "oauth", "bearer"]


class IntegrationTool(BaseModel):
    """Tool metadata for frontend display (not used by LLM)."""

    name: str
    description: str | None = None


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

    integration_id: str = Field(..., description="Unique identifier for the integration")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="User-facing description")
    category: str = Field(..., description="e.g., productivity, communication, developer")

    # Management and source
    managed_by: Literal["self", "composio", "mcp", "internal"] = Field(
        ..., description="Which system manages the integration"
    )
    source: Literal["platform", "custom"] = Field(
        "custom", description="Platform (from code) or custom (user-created)"
    )

    # Visibility and ownership
    is_public: bool = Field(False, description="Visible in public marketplace")
    created_by: str | None = Field(None, description="User ID for custom integrations")

    # Publishing metadata
    published_at: datetime | None = Field(
        None, description="When integration was published to marketplace"
    )
    clone_count: int = Field(0, description="Number of times this integration was cloned")
    # Note: cloned_from, slug, og_title, og_description, creator_name, creator_picture
    # have been removed. Creator info is now fetched from users collection at runtime.

    # Configuration (one of these based on managed_by)
    mcp_config: MCPConfig | None = None
    composio_config: ComposioConfigDoc | None = None

    # Frontend display metadata
    tools: list[IntegrationTool] = Field(
        default_factory=list, description="Tool list for frontend display only"
    )
    icon_url: str | None = Field(None, description="Favicon URL fetched from MCP server subdomain")
    display_priority: int = Field(0, description="Higher priority shows first")
    is_featured: bool = Field(False, description="Show in featured section")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    @field_validator("clone_count", mode="before")
    @classmethod
    def coerce_clone_count(cls, v):
        """Coerce None to 0 for clone_count."""
        return v if v is not None else 0

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    connected_at: datetime | None = Field(None, description="When OAuth/auth was completed")

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class AddUserIntegrationRequest(BaseModel):
    """Request to add an integration to user's workspace."""

    integration_id: str = Field(..., description="ID of integration to add")


class CreateCustomIntegrationRequest(BaseModel):
    """Request to create a custom MCP integration."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    category: str = Field(default="custom")
    server_url: str = Field(..., description="MCP server URL")
    requires_auth: bool = Field(False)
    auth_type: Literal["none", "oauth", "bearer"] | None = Field(None)
    is_public: bool = Field(False)
    bearer_token: str | None = Field(None)


class UpdateCustomIntegrationRequest(BaseModel):
    """Request to update a custom integration (partial update)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=500)
    server_url: str | None = None
    requires_auth: bool | None = None
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    is_public: bool | None = None


class IntegrationResponse(BaseModel):
    """Integration details for API responses."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

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
    auth_type: Literal["none", "oauth", "bearer"] | None = None

    # Tool metadata for frontend display
    tools: list[IntegrationTool] = Field(default_factory=list)

    # Icon URL for custom integrations (favicon from MCP server)
    icon_url: str | None = None

    # Custom integration fields
    is_public: bool | None = None
    created_by: str | None = None

    # Publishing metadata (for public integrations)
    published_at: datetime | None = None
    clone_count: int = 0
    slug: str | None = None
    # Creator info (populated via aggregation from users collection)
    creator: dict[str, str | None] | None = None

    @field_validator("clone_count", mode="before")
    @classmethod
    def coerce_clone_count(cls, v):
        """Coerce None to 0 for clone_count."""
        return v if v is not None else 0

    @classmethod
    def from_integration(cls, integration: Integration) -> "IntegrationResponse":
        """Convert Integration model to response."""
        requires_auth = False
        auth_type = None

        if integration.mcp_config:
            requires_auth = integration.mcp_config.requires_auth
            auth_type = integration.mcp_config.auth_type or ("oauth" if requires_auth else "none")

        # Compute slug at runtime (not stored in DB)
        slug = generate_integration_slug(
            name=integration.name,
            category=integration.category,
            integration_id=integration.integration_id,
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
            published_at=integration.published_at,
            clone_count=integration.clone_count or 0,
            slug=slug,
        )

    @classmethod
    def from_oauth_integration(cls, oauth_int: OAuthIntegration) -> "IntegrationResponse":
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
            auth_type=cast(AuthType, auth_type) if auth_type else None,
            tools=[],  # Platform tools are loaded live, not stored
            slug=oauth_int.id,  # Platform integrations use ID as slug
        )


class UserIntegrationResponse(BaseModel):
    """User integration with hydrated integration details."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    integration_id: str
    status: Literal["created", "connected"]
    created_at: datetime
    connected_at: datetime | None = None

    # Hydrated integration details
    integration: IntegrationResponse


class MarketplaceResponse(BaseModel):
    """Response for marketplace listing."""

    featured: list[IntegrationResponse] = Field(default_factory=list)
    integrations: list[IntegrationResponse] = Field(default_factory=list)
    total: int = 0


class UserIntegrationsListResponse(BaseModel):
    """Response for user's integrations listing."""

    integrations: list[UserIntegrationResponse] = Field(default_factory=list)
    total: int = 0


class ConnectIntegrationRequest(BaseModel):
    """Request to connect an integration."""

    redirect_path: str = Field(
        default="/integrations",
        description="Frontend path to redirect after OAuth completes",
    )
    bearer_token: str | None = Field(None)


class ConnectIntegrationResponse(BaseModel):
    """
    Unified response for integration connection.

    Frontend handles response based on status:
    - connected: Integration is ready to use
    - redirect: OAuth required, frontend should redirect to url
    - error: Connection failed
    """

    status: Literal["connected", "redirect", "error"]
    integration_id: str
    message: str | None = None

    # For status="connected"
    tools_count: int | None = None

    # For status="redirect"
    redirect_url: str | None = None

    # For status="error"
    error: str | None = None


# TypedDicts for integration tool LLM responses


class IntegrationInfo(TypedDict):
    """Integration information returned to LLM for context."""

    id: str
    name: str
    description: str
    category: str
    connected: bool


class SuggestedIntegration(TypedDict):
    """Suggested public integration from marketplace search."""

    id: str
    name: str
    description: str
    category: str
    icon_url: str | None
    auth_type: str | None
    relevance_score: float
    slug: str


class ListIntegrationsResult(TypedDict):
    """Result from list_integrations tool for LLM context."""

    connected: list[IntegrationInfo]
    available: list[IntegrationInfo]
    suggested: list[SuggestedIntegration]
