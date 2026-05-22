"""OAuth integration models."""

from typing import Literal

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

    use_cases: list[str] = []
    how_it_works: list[IntegrationHowItWorksStep] = []
    faqs: list[IntegrationFAQ] = []


class OAuthIntegration(BaseModel):
    """OAuth integration configuration."""

    id: str
    name: str
    description: str
    category: str
    provider: str
    scopes: list[OAuthScope]
    available: bool = True
    oauth_endpoints: dict[str, str] | None = None
    is_special: bool = False
    display_priority: int = 0
    included_integrations: list[str] = []
    is_featured: bool = False
    short_name: str | None = None
    managed_by: Literal["self", "composio", "mcp", "internal"]
    composio_config: ComposioConfig | None = None
    mcp_config: MCPConfig | None = None
    associated_triggers: list[TriggerConfig] = []
    subagent_config: SubAgentConfig | None = None
    metadata_config: ProviderMetadataConfig | None = None
    content: IntegrationContent | None = None

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
                f"Integration {self.id!r} has managed_by='composio' but no composio_config."
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
    includedIntegrations: list[str]
    isFeatured: bool
    managedBy: Literal["self", "composio", "mcp", "internal"]
    authType: Literal["none", "oauth", "bearer"] | None = None
    source: Literal["platform"] = "platform"
