"""OAuth integration models."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, model_validator

from app.models.mcp_config import (
    ComposioConfig,
    MCPConfig,
    OAuthScope,
    ProviderMetadataConfig,
    SubAgentConfig,
)
from app.models.trigger_config import TriggerConfig


class IntegrationHowItWorksStep(BaseModel):
    """A single step in the 'How it works' section."""

    title: str
    body: str


class IntegrationFAQ(BaseModel):
    """A single FAQ entry for the integration detail page."""

    question: str
    answer: str


class IntegrationContent(BaseModel):
    """Rich marketplace content shown only on the integration detail page."""

    use_cases: List[str] = []
    how_it_works: List[IntegrationHowItWorksStep] = []
    faqs: List[IntegrationFAQ] = []


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
    content: Optional[IntegrationContent] = None

    @model_validator(mode="after")
    def _enforce_composio_invariant(self) -> "OAuthIntegration":
        # `provider_subagents.py` selects the Composio branch using
        # `managed_by == "composio"` and then expects `composio_config` to
        # be present. Pin the bidirectional invariant so a future config
        # entry can't silently skip Composio tool registration.
        if self.composio_config is not None and self.managed_by != "composio":
            raise ValueError(
                f"Integration {self.id!r} sets composio_config but "
                f"managed_by={self.managed_by!r}; expected 'composio'."
            )
        if self.managed_by == "composio" and self.composio_config is None:
            raise ValueError(
                f"Integration {self.id!r} has managed_by='composio' but "
                f"no composio_config."
            )
        return self


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
