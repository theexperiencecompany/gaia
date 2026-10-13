"""The admin's Composio setup: which auth config each integration connects through."""

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


class ComposioSetupResponse(ResponseModel):
    """GET /setup/composio: the per-integration view the admin panel renders."""

    composio_configured: bool = Field(description="Whether a Composio API key resolves")
    integrations: list[ComposioIntegrationSetup]


class SaveComposioAuthConfigsRequest(BaseModel):
    """The full set of auth config ids to store; integrations left out are cleared."""

    auth_configs: dict[str, str] = Field(description="Integration id to Composio auth config id")
