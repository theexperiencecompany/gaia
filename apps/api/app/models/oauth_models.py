"""OAuth integration models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel

from app.models.cli_config import CliConfig
from app.models.integration_provider import ManagedBy
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
    """Rich marketplace content shown only on the integration detail page.

    Serializes with camelCase aliases (use_cases -> useCases, how_it_works ->
    howItWorks) so the nested object matches the camelCase contract the rest of
    the public integration response already uses; without this the frontend
    receives snake_case keys and silently falls back to generic content.
    """

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

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
    managed_by: ManagedBy
    composio_config: ComposioConfig | None = None
    mcp_config: MCPConfig | None = None
    cli_config: CliConfig | None = None
    # Tool names/slugs this integration's HIL gate must treat as destructive
    # (e.g. GMAIL_SEND_EMAIL). Integration-agnostic — applies to Composio and
    # built-in MCP configs alike. ``None`` = uncurated: the HIL LLM classifier
    # resolves each tool at gate time and fails closed. A list (possibly empty)
    # = reviewed: exactly those are destructive, the rest safe.
    destructive_tools: list[str] | None = None
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
        # Same bidirectional invariant for the CLI transport: the connect
        # dispatch and the tool factory both select on managed_by == "cli" and
        # then require cli_config, so a mismatch would surface as a connect
        # that resolves to nothing rather than a config error at import.
        if self.cli_config is not None and self.managed_by != "cli":
            raise ValueError(
                f"Integration {self.id!r} sets cli_config but "
                f"managed_by={self.managed_by!r}; expected 'cli'."
            )
        if self.managed_by == "cli" and self.cli_config is None:
            raise ValueError(f"Integration {self.id!r} has managed_by='cli' but no cli_config.")
        return self


class MobileLoginUrlResponse(BaseModel):
    """The hosted authorization URL a mobile client should open."""

    url: str


class OAuthClientMetadataResponse(BaseModel):
    """The OAuth Client ID Metadata Document authorization servers fetch.

    Shape is fixed by draft-ietf-oauth-client-id-metadata-document-00 §4.1;
    ``client_id`` MUST equal this document's own URL and
    ``token_endpoint_auth_method`` MUST be ``"none"``.
    """

    client_id: str
    client_name: str
    client_uri: str
    logo_uri: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: Literal["none"] = "none"
