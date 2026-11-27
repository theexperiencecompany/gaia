"""The integration cards' payloads: connect prompts, marketplace suggestions and connect buttons."""

from pydantic import Field

from app.schemas.common import ResponseModel


class ReconnectAccount(ResponseModel):
    """The expired account a connect card signs back in."""

    id: str
    name: str


class IntegrationConnectionData(ResponseModel):
    """The integration_connection_required card: an integration the run needs the user to connect."""

    integration_id: str
    integration_name: str
    expired: bool
    add_account: bool
    message: str
    connected_accounts: list[str]
    reconnect_account: ReconnectAccount | None


class SuggestedIntegrationCard(ResponseModel):
    """A marketplace integration the user can add, in the card's camelCase."""

    id: str
    name: str
    description: str
    category: str
    icon_url: str | None = Field(serialization_alias="iconUrl")
    auth_type: str | None = Field(serialization_alias="authType")
    relevance_score: float = Field(serialization_alias="relevanceScore")
    slug: str


class IntegrationListCard(ResponseModel):
    """The integration_list_data card: the marketplace integrations a list search suggested."""

    has_suggestions: bool = Field(serialization_alias="hasSuggestions")
    suggested: list[SuggestedIntegrationCard]


class ConnectOption(ResponseModel):
    """One connect button; integration_id is None for the button opening every integration."""

    integration_id: str | None = None
    label: str
    href: str


class ConnectOptionsData(ResponseModel):
    """The connect_options card: the buttons under the first conversation's routines bubble."""

    options: list[ConnectOption]
