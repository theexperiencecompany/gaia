"""Integration response models with camelCase aliases."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import SuccessResponse


class IntegrationConfigItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    category: str
    provider: str
    available: bool
    is_special: bool = Field(alias="isSpecial")
    display_priority: int = Field(alias="displayPriority")
    included_integrations: List[str] = Field(alias="includedIntegrations")
    is_featured: bool = Field(alias="isFeatured")
    managed_by: Literal["self", "composio", "mcp", "internal"] = Field(
        alias="managedBy"
    )
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = Field(
        None, alias="authType"
    )
    source: Literal["platform"] = "platform"


class IntegrationsConfigResponse(BaseModel):
    integrations: List[IntegrationConfigItem]


class IntegrationStatusItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")
    connected: bool


class IntegrationsStatusResponse(BaseModel):
    integrations: List[IntegrationStatusItem]


class IntegrationSuccessResponse(SuccessResponse):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")


class AddUserIntegrationResponse(SuccessResponse):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")
    connection_status: Literal["created", "connected"] = Field(alias="connectionStatus")


class CustomIntegrationConnectionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["created", "connected", "requires_oauth", "failed"]
    tools_count: Optional[int] = Field(None, alias="toolsCount")
    oauth_url: Optional[str] = Field(None, alias="oauthUrl")
    error: Optional[str] = None


class CreateCustomIntegrationResponse(SuccessResponse):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")
    name: str
    connection: CustomIntegrationConnectionResult


class IntegrationTool(BaseModel):
    name: str
    description: Optional[str] = None


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")
    name: str
    description: str
    category: str
    managed_by: Literal["self", "composio", "mcp", "internal"] = Field(
        alias="managedBy"
    )
    source: Literal["platform", "custom"]
    is_featured: bool = Field(alias="isFeatured")
    display_priority: int = Field(alias="displayPriority")
    requires_auth: bool = Field(False, alias="requiresAuth")
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = Field(
        None, alias="authType"
    )
    tools: List[IntegrationTool] = Field(default_factory=list)
    icon_url: Optional[str] = Field(None, alias="iconUrl")
    is_public: Optional[bool] = Field(None, alias="isPublic")
    created_by: Optional[str] = Field(None, alias="createdBy")


class UserIntegrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    integration_id: str = Field(alias="integrationId")
    status: Literal["created", "connected"]
    created_at: datetime = Field(alias="createdAt")
    connected_at: Optional[datetime] = Field(None, alias="connectedAt")
    integration: IntegrationResponse


class MarketplaceResponse(BaseModel):
    featured: List[IntegrationResponse] = Field(default_factory=list)
    integrations: List[IntegrationResponse] = Field(default_factory=list)
    total: int = 0


class UserIntegrationsListResponse(BaseModel):
    integrations: List[UserIntegrationResponse] = Field(default_factory=list)
    total: int = 0


class ConnectIntegrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["connected", "redirect", "error"]
    integration_id: str = Field(alias="integrationId")
    message: Optional[str] = None
    tools_count: Optional[int] = Field(None, alias="toolsCount")
    redirect_url: Optional[str] = Field(None, alias="redirectUrl")
    error: Optional[str] = None
