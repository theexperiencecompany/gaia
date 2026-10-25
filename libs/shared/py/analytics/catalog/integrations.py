"""Integration, MCP and skill events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "IntegrationAccountAdded",
    "IntegrationAccountRemoved",
    "IntegrationAccountRenamed",
    "IntegrationConnectInitiated",
    "IntegrationConnected",
    "IntegrationCustomDeleted",
    "IntegrationCustomPublished",
    "IntegrationCustomUnpublished",
    "IntegrationCustomUpdated",
    "IntegrationDisconnected",
    "IntegrationError",
    "IntegrationInstanceSetupSaved",
    "IntegrationToolkitDisabled",
    "IntegrationToolkitEnabled",
    "IntegrationPrimaryChanged",
    "McpConnectionTested",
    "SkillDisabled",
    "SkillEnabled",
    "SkillInstalled",
    "SkillSearched",
    "SkillUninstalled",
    "SkillUpdated",
]


class IntegrationConnected(ServerEvent):
    """An integration or platform account finished connecting."""

    event: ClassVar[str] = "integration:connected"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier
    auth_type: Literal["bearer", "none"] | None = None
    source: Literal["marketplace", "workspace"] | None = None
    managed_by: Identifier | None = None
    connection_method: Literal["oauth"] | None = None
    provider: Identifier | None = None
    is_new_link: bool | None = None
    # The user signed in again to an account they already had (an expiry or re-auth). A further
    # account on a multi-account integration is a new connect, not a reconnect.
    is_reconnect: bool | None = None


class IntegrationConnectInitiated(ServerEvent):
    """A connect flow was started and the user sent off to authorize it."""

    event: ClassVar[str] = "integration:connect_initiated"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier
    auth_type: Identifier | None = None
    managed_by: Identifier | None = None
    source: Literal["connect_link"] | None = None


class IntegrationDisconnected(ServerEvent):
    """An integration or platform account was disconnected."""

    event: ClassVar[str] = "integration:disconnected"
    budget_per_user_day: ClassVar[int] = 30

    integration_id: Identifier


class IntegrationAccountAdded(ServerEvent):
    """An account was authorized on a multi-account integration, or replaced one with its identity."""

    event: ClassVar[str] = "integration:account_added"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier
    account_count: int
    replaced: bool
    has_identity: bool


class IntegrationAccountRemoved(ServerEvent):
    """One account of an integration was disconnected; 0 left means the integration went too."""

    event: ClassVar[str] = "integration:account_removed"
    budget_per_user_day: ClassVar[int] = 20

    integration_id: Identifier
    account_count: int


class IntegrationAccountRenamed(ServerEvent):
    """An account of an integration was given a name, or had it cleared."""

    event: ClassVar[str] = "integration:account_renamed"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier
    cleared: bool


class IntegrationPrimaryChanged(ServerEvent):
    """Another account became an integration's primary, the one triggers and defaults use."""

    event: ClassVar[str] = "integration:primary_changed"
    budget_per_user_day: ClassVar[int] = 20

    integration_id: Identifier
    account_count: int


class IntegrationInstanceSetupSaved(ServerEvent):
    """A self-host admin saved which Composio auth config each integration connects through."""

    event: ClassVar[str] = "integration:instance_setup_saved"
    budget_per_user_day: ClassVar[int] = 50

    stored_count: int
    set_up_count: int
    total_count: int


class IntegrationToolkitEnabled(ServerEvent):
    """A self-host admin enabled a Composio toolkit; GAIA created its auth config."""

    event: ClassVar[str] = "integration:toolkit_enabled"
    budget_per_user_day: ClassVar[int] = 50

    toolkit: Identifier
    origin: Literal["code", "instance"]
    composio_managed: bool


class IntegrationToolkitDisabled(ServerEvent):
    """A self-host admin removed a Composio toolkit they had enabled."""

    event: ClassVar[str] = "integration:toolkit_disabled"
    budget_per_user_day: ClassVar[int] = 50

    toolkit: Identifier


class IntegrationCustomUpdated(ServerEvent):
    """A user edited a custom integration."""

    event: ClassVar[str] = "integration:custom_updated"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier


class IntegrationCustomDeleted(ServerEvent):
    """A user deleted a custom integration."""

    event: ClassVar[str] = "integration:custom_deleted"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier


class IntegrationCustomPublished(ServerEvent):
    """A user published a custom integration to the marketplace."""

    event: ClassVar[str] = "integration:custom_published"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier


class IntegrationCustomUnpublished(ServerEvent):
    """A user unpublished a custom integration."""

    event: ClassVar[str] = "integration:custom_unpublished"
    budget_per_user_day: ClassVar[int] = 50

    integration_id: Identifier


class IntegrationError(WebEvent):
    """A connect or disconnect request failed in the browser."""

    event: ClassVar[str] = "integration:error"
    budget_per_user_day: ClassVar[int] = 10

    integration: Identifier
    # The failed request's HTTP status (0 for a transport failure) and the API's machine code; never its message.
    status: int | None = None
    error_code: Identifier | None = None


class McpConnectionTested(ServerEvent):
    """An MCP server connection probe finished."""

    event: ClassVar[str] = "mcp:connection_tested"
    budget_per_user_day: ClassVar[int] = 50

    status: Literal["connected", "failed", "requires_oauth"]
    tools_count: int | None = None


class SkillInstalled(ServerEvent):
    """A skill was installed from GitHub, written inline, or learned by GAIA's agent."""

    event: ClassVar[str] = "skill:installed"
    budget_per_user_day: ClassVar[int] = 10

    target: Identifier
    source: Literal["github", "inline", "learned"]
    # Who did it: "user" in Settings, or "agent" for GAIA's own skill tools.
    author: Identifier
    skill_id: Identifier | None = None


class SkillUpdated(ServerEvent):
    """A skill's instructions were edited, by the user or by GAIA's agent."""

    event: ClassVar[str] = "skill:updated"
    budget_per_user_day: ClassVar[int] = 50

    target: Identifier
    # Who did it: "user" in Settings, or "agent" for GAIA's own skill tools.
    author: Identifier


class SkillEnabled(ServerEvent):
    """A user enabled a skill."""

    event: ClassVar[str] = "skill:enabled"
    budget_per_user_day: ClassVar[int] = 50


class SkillDisabled(ServerEvent):
    """A user disabled a skill."""

    event: ClassVar[str] = "skill:disabled"
    budget_per_user_day: ClassVar[int] = 50


class SkillUninstalled(ServerEvent):
    """A user uninstalled a skill."""

    event: ClassVar[str] = "skill:uninstalled"
    budget_per_user_day: ClassVar[int] = 50

    skill_id: Identifier
    target: Identifier


class SkillSearched(WebEvent):
    """A user paused typing in the skills search box; the filter is client-side."""

    event: ClassVar[str] = "skill:searched"
    budget_per_user_day: ClassVar[int] = 50
