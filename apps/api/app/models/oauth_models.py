"""OAuth integration models."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from app.models.mcp_config import (
    ComposioConfig,
    MCPConfig,
    OAuthScope,
    ProviderMetadataConfig,
    SubAgentConfig,
)
from app.models.trigger_config import TriggerConfig


class OAuthIntegration(BaseModel):
    """OAuth integration configuration."""

    id: str
    name: str
    description: str
    category: str
    provider: str
    scopes: List[OAuthScope]
    available: bool = True
    oauth_endpoints: Optional[Dict[str, str]] = None
    is_special: bool = False
    display_priority: int = 0
    included_integrations: List[str] = []
    is_featured: bool = False
    short_name: Optional[str] = None
    managed_by: Literal["self", "composio", "mcp", "internal"]
    composio_config: Optional[ComposioConfig] = None
    mcp_config: Optional[MCPConfig] = None
    associated_triggers: List[TriggerConfig] = []
    subagent_config: Optional[SubAgentConfig] = None
    metadata_config: Optional[ProviderMetadataConfig] = None


class IntegrationConfigResponse(BaseModel):
    """Response model for integration configuration."""

    id: str
    name: str
    description: str
    category: str
    provider: str
    available: bool
    isSpecial: bool
    displayPriority: int
    includedIntegrations: List[str]
    isFeatured: bool
    managedBy: Literal["self", "composio", "mcp", "internal"]
    authType: Optional[Literal["none", "oauth", "bearer"]] = None
    source: Literal["platform"] = "platform"
