"""Integration response models with camelCase aliases."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas.common import SuccessResponse


# Base model that auto-converts snake_case to camelCase for JSON serialization
class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


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


class IntegrationResponse(CamelModel):
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
