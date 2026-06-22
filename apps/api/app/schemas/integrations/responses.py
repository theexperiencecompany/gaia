"""Integration response models with camelCase aliases."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from app.models.integration_instructions_models import InstructionsEditor
from app.models.oauth_models import IntegrationContent
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
    included_integrations: list[str]
    is_featured: bool
    managed_by: Literal["self", "composio", "mcp", "internal"]
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    requires_auth: bool = False
    source: Literal["platform"] = "platform"
    slug: str  # For platform integrations, this is the same as id


class IntegrationsConfigResponse(BaseModel):
    integrations: list[IntegrationConfigItem]


class IntegrationSuccessResponse(SuccessResponse, CamelModel):
    integration_id: str


class AddUserIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    connection_status: Literal["created", "connected"]


class IntegrationInstructionsResponse(CamelModel):
    """A user's custom instructions for one integration."""

    integration_id: str
    content: str
    updated_by: InstructionsEditor
    updated_at: datetime | None = None


class CustomIntegrationConnectionResult(CamelModel):
    status: Literal["created", "connected", "requires_oauth", "failed"]
    tools_count: int | None = None
    oauth_url: str | None = None
    error: str | None = None


class CreateCustomIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    name: str
    connection: CustomIntegrationConnectionResult


class IntegrationTool(BaseModel):
    name: str
    description: str | None = None


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
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    tools: list[IntegrationTool] = []
    icon_url: str | None = None
    is_public: bool | None = None
    created_by: str | None = None

    # Publishing fields
    published_at: datetime | None = None
    clone_count: int = 0
    slug: str | None = None  # Computed at runtime via generate_integration_slug
    # Creator info (populated via aggregation from users collection)
    creator: Optional["CommunityIntegrationCreator"] = None


class MarketplaceResponse(BaseModel):
    featured: list[IntegrationResponse] = []
    integrations: list[IntegrationResponse] = []
    total: int = 0


class MyIntegrationItem(CamelModel, CloneCountMixin):
    """One integration as it pertains to the current user: catalog metadata plus
    their connection `status`, without the heavy per-tool schemas (only `tool_count`).
    Fetch full tools on demand from `GET /integrations/{id}/tools`.
    """

    id: str
    name: str
    description: str
    category: str
    source: Literal["platform", "custom"]
    managed_by: Literal["self", "composio", "mcp", "internal"]
    status: Literal["connected", "created", "not_connected"]
    requires_auth: bool = False
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    is_featured: bool = False
    display_priority: int = 0
    available: bool = True
    icon_url: str | None = None
    slug: str | None = None
    tool_count: int = 0
    # Custom-integration fields (None/0 for platform entries).
    is_public: bool | None = None
    created_by: str | None = None
    published_at: datetime | None = None
    clone_count: int = 0
    creator: Optional["CommunityIntegrationCreator"] = None


class MyIntegrationsResponse(BaseModel):
    """The full integration catalog personalized for one user (platform + their
    own custom integrations), each carrying connection status. Replaces the
    client-side merge of /config + /status + /users/me/integrations."""

    integrations: list[MyIntegrationItem] = []
    total: int = 0


class IntegrationToolsResponse(CamelModel):
    """Full tool list for a single integration (catalog data, on demand)."""

    integration_id: str
    tools: list[IntegrationTool] = []
    count: int = 0


class ConnectIntegrationResponse(CamelModel):
    status: Literal["connected", "redirect", "error"]
    integration_id: str
    name: str
    message: str | None = None
    tools_count: int | None = None
    redirect_url: str | None = None
    error: str | None = None


class PublishIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str
    public_url: str


class UnpublishIntegrationResponse(SuccessResponse, CamelModel):
    integration_id: str


class CommunityIntegrationCreator(CamelModel):
    """Creator info for community integration display."""

    name: str | None = None
    picture: str | None = None


class CommunityIntegrationItem(CamelModel, CloneCountMixin):
    """Integration item for community marketplace listing."""

    integration_id: str
    slug: str
    name: str
    description: str
    category: str
    icon_url: str | None = None
    clone_count: int = 0
    tool_count: int = 0
    tools: list[IntegrationTool] = []
    published_at: datetime | None = None
    creator: CommunityIntegrationCreator | None = None


class CommunityListResponse(BaseModel):
    """Response for community marketplace listing."""

    integrations: list[CommunityIntegrationItem] = []
    total: int = 0
    has_more: bool = False


class MCPConfigDetail(CamelModel):
    """MCP config for public display."""

    server_url: str | None = None
    requires_auth: bool = False
    auth_type: Literal["none", "oauth", "bearer"] | None = None


class PublicIntegrationDetailResponse(CamelModel, CloneCountMixin):
    """Full public integration details for public pages (SEO/sharing)."""

    integration_id: str
    slug: str
    name: str
    description: str
    category: str
    icon_url: str | None = None

    # Creator info (nested object populated via aggregation from users collection)
    creator: CommunityIntegrationCreator | None = None

    # MCP config for public display (nested object for frontend compatibility)
    mcp_config: MCPConfigDetail | None = None

    # Tools list
    tools: list[IntegrationTool] = []

    # Stats
    clone_count: int = 0
    tool_count: int = 0
    published_at: datetime | None = None

    # Source type (platform or custom)
    source: Literal["platform", "custom"] | None = None
    auth_type: Literal["none", "oauth", "bearer"] | None = None

    # Rich content — only present for native (platform) integrations
    content: IntegrationContent | None = None


class AddIntegrationResponse(CamelModel):
    """Response for adding a public integration to user's workspace."""

    integration_id: str
    name: str
    status: Literal["connected", "redirect", "error"]
    message: str = "Integration added successfully"
    redirect_url: str | None = None
    tools_count: int | None = None
    error: str | None = None


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
    icon_url: str | None = None


class SearchIntegrationsResponse(BaseModel):
    """Response for semantic search of integrations."""

    integrations: list[SearchIntegrationItem] = []
    query: str
