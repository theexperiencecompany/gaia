"""The admin's Composio setup: auth configs per integration, and the toolkit catalog."""

from typing import Literal

from pydantic import BaseModel, Field

from app.constants.integrations import ComposioAuthConfigSource
from app.schemas.common import ResponseModel


class ComposioAuthConfigCandidate(ResponseModel):
    """An enabled auth config in the admin's Composio project for this integration's toolkit."""

    id: str = Field(description="Composio auth config id (ac_...)")
    name: str = Field(description="Name the admin gave it in Composio")


class ComposioIntegrationSetup(ResponseModel):
    """One Composio integration and the auth config it connects through on this instance."""

    integration_id: str
    name: str
    toolkit: str = Field(description="Composio toolkit slug the auth config must belong to")
    auth_config_id: str | None = Field(description="The id in effect; None means not set up")
    source: ComposioAuthConfigSource | None = Field(description="Where the id in effect comes from")
    detected: list[ComposioAuthConfigCandidate] = Field(
        description="Matching auth configs found in the Composio project"
    )
    origin: Literal["code", "instance"] = Field(
        description="instance: a toolkit the admin enabled from the catalog"
    )
    icon_url: str | None = Field(description="Logo for integrations GAIA ships no icon for")


class ComposioSetupResponse(ResponseModel):
    """GET /setup/composio: the per-integration view the admin panel renders."""

    composio_configured: bool = Field(description="Whether a Composio API key resolves")
    integrations: list[ComposioIntegrationSetup]


class SaveComposioAuthConfigsRequest(BaseModel):
    """The full set of auth config ids to store; integrations left out are cleared."""

    auth_configs: dict[str, str] = Field(description="Integration id to Composio auth config id")


ComposioToolkitStatus = Literal["built_in", "enabled", "available", "unsupported"]


class ComposioToolkit(ResponseModel):
    """One toolkit in Composio's catalog, as the admin's catalog browser shows it."""

    slug: str
    name: str
    description: str
    logo: str | None
    categories: list[str]
    auth_schemes: list[str]
    composio_managed: bool = Field(description="Composio can sign users in with its own app")
    no_auth: bool
    tools_count: int
    triggers_count: int


class ComposioCatalogEntry(ComposioToolkit):
    """A catalog toolkit plus what it is on this instance."""

    status: ComposioToolkitStatus = Field(
        description="built_in: defined in GAIA's code; enabled: added by the admin; "
        "available: can be enabled; unsupported: needs no sign-in, which GAIA cannot connect yet"
    )
    integration_id: str | None = Field(description="The GAIA integration it backs, if any")
    set_up: bool = Field(description="Whether that integration has an auth config here")


class ComposioCatalogResponse(ResponseModel):
    """GET /setup/composio/toolkits: one page of the searched catalog."""

    items: list[ComposioCatalogEntry]
    total: int = Field(description="Matches across all pages")
    categories: list[str] = Field(description="Every category in the catalog, for the filter")


class ComposioAuthField(ResponseModel):
    """A value the admin must supply to create the toolkit's auth config."""

    name: str
    display_name: str
    description: str
    required: bool
    is_secret: bool


class ComposioToolkitDetailResponse(ResponseModel):
    """GET /setup/composio/toolkits/{slug}: how enabling this toolkit will authenticate."""

    toolkit: ComposioCatalogEntry
    auth_scheme: str | None = Field(description="The scheme GAIA will create; None if unsupported")
    composio_managed: bool = Field(description="Whether that scheme uses Composio's own app")
    fields: list[ComposioAuthField] = Field(
        description="Values to send with the enable request; empty means one click"
    )


class EnableComposioToolkitRequest(BaseModel):
    """Values for the auth config's creation fields, keyed by field name."""

    credentials: dict[str, str] = Field(default_factory=dict)


class EnableComposioToolkitResponse(ResponseModel):
    """The integration the toolkit now backs and the auth config created for it."""

    integration_id: str
    auth_config_id: str
    origin: Literal["code", "instance"]
    composio_managed: bool = Field(description="Users sign in through Composio's own app")
