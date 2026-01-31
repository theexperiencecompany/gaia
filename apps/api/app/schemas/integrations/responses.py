"""Integration response models with camelCase aliases."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from app.schemas.common import SuccessResponse


# Base model that auto-converts snake_case to camelCase for JSON serialization
class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class CloneCountMixin(BaseModel):
    """Mixin to handle clone_count None -> 0 coercion."""

    @field_validator("clone_count", mode="before", check_fields=False)
    @classmethod
    def coerce_clone_count(cls, v):
        """Coerce None to 0 for clone_count."""
        return v if v is not None else 0


class IntegrationConfigItem(CamelModel):
    id: str
    name: str
    description: str
    category: str
    provider: str
    available: bool
    is_special: bool
    display_priority: int
    included_integrations: List[str]
    is_featured: bool
    managed_by: Literal["self", "composio", "mcp", "internal"]
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    source: Literal["platform"] = "platform"
    slug: str  # For platform integrations, this is the same as id


class IntegrationsConfigResponse(BaseModel):
    integrations: List[IntegrationConfigItem]


class IntegrationStatusItem(CamelModel):
    integration_id: str
    connected: bool


class IntegrationsStatusResponse(BaseModel):
    integrations: List[IntegrationStatusItem]


class IntegrationSuccessResponse(SuccessResponse, CamelModel):
    integration_id: str


class AddUserIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    connection_status: Literal["created", "connected"]


class CustomIntegrationConnectionResult(CamelModel):
    status: Literal["created", "connected", "requires_oauth", "failed"]
    tools_count: Optional[int] = None
    oauth_url: Optional[str] = None
    error: Optional[str] = None


class CreateCustomIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    name: str
    connection: CustomIntegrationConnectionResult


class IntegrationTool(BaseModel):
    name: str
    description: Optional[str] = None


class IntegrationResponse(CamelModel, CloneCountMixin):
    """Integration details for API responses."""

    integration_id: str
    name: str
    description: str
    category: str
    managed_by: Literal["self", "composio", "mcp", "internal"]
    source: Literal["platform", "custom"]
    is_featured: bool
    display_priority: int
    requires_auth: bool = False
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    tools: List[IntegrationTool] = []
    icon_url: Optional[str] = None
    is_public: Optional[bool] = None
    created_by: Optional[str] = None

    # Publishing fields
    published_at: Optional[datetime] = None
    clone_count: int = 0
    slug: Optional[str] = None  # Computed at runtime via generate_integration_slug
    # Creator info (populated via aggregation from users collection)
    creator: Optional["CommunityIntegrationCreator"] = None


class UserIntegrationResponse(CamelModel):
    integration_id: str
    status: Literal["created", "connected"]
    created_at: datetime
    connected_at: Optional[datetime] = None
    integration: IntegrationResponse


class MarketplaceResponse(BaseModel):
    featured: List[IntegrationResponse] = []
    integrations: List[IntegrationResponse] = []
    total: int = 0


class UserIntegrationsListResponse(BaseModel):
    integrations: List[UserIntegrationResponse] = []
    total: int = 0


class ConnectIntegrationResponse(CamelModel):
    status: Literal["connected", "redirect", "error"]
    integration_id: str
    message: Optional[str] = None
    tools_count: Optional[int] = None
    redirect_url: Optional[str] = None
    error: Optional[str] = None


class PublishIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    public_url: str


class UnpublishIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str


class CommunityIntegrationCreator(CamelModel):
    """Creator info for community integration display."""

    name: Optional[str] = None
    picture: Optional[str] = None


class CommunityIntegrationItem(CamelModel, CloneCountMixin):
    """Integration item for community marketplace listing."""

    integration_id: str
    slug: str
    name: str
    description: str
    category: str
    icon_url: Optional[str] = None
    clone_count: int = 0
    tool_count: int = 0
    tools: List[IntegrationTool] = []
    published_at: Optional[datetime] = None
    creator: Optional[CommunityIntegrationCreator] = None


class CommunityListResponse(BaseModel):
    """Response for community marketplace listing."""

    integrations: List[CommunityIntegrationItem] = []
    total: int = 0
    has_more: bool = False


class MCPConfigDetail(CamelModel):
    """MCP config for public display."""

    server_url: Optional[str] = None
    requires_auth: bool = False
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None


class PublicIntegrationDetailResponse(CamelModel, CloneCountMixin):
    """Full public integration details for public pages (SEO/sharing)."""

    integration_id: str
    slug: str
    name: str
    description: str
    category: str
    icon_url: Optional[str] = None

    # Creator info (nested object populated via aggregation from users collection)
    creator: Optional[CommunityIntegrationCreator] = None

    # MCP config for public display (nested object for frontend compatibility)
    mcp_config: Optional[MCPConfigDetail] = None

    # Tools list
    tools: List[IntegrationTool] = []

    # Stats
    clone_count: int = 0
    tool_count: int = 0
    published_at: Optional[datetime] = None


class AddIntegrationResponse(CamelModel):
    """Response for adding a public integration to user's workspace."""

    integration_id: str
    name: str
    status: Literal["connected", "redirect", "error"]
    message: str = "Integration added successfully"
    redirect_url: Optional[str] = None
    tools_count: Optional[int] = None
    error: Optional[str] = None


class SearchIntegrationItem(CamelModel, CloneCountMixin):
    """Integration item in search results."""

    integration_id: str
    slug: str
    name: str
    description: str
    category: str
    relevance_score: float
    clone_count: int = 0
    tool_count: int = 0
    icon_url: Optional[str] = None


class SearchIntegrationsResponse(BaseModel):
    """Response for semantic search of integrations."""

    integrations: List[SearchIntegrationItem] = []
    query: str
