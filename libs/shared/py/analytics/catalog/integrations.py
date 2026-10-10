"""Integration, MCP and skill events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "IntegrationConnectInitiated",
    "IntegrationConnected",
    "IntegrationCustomDeleted",
    "IntegrationCustomPublished",
    "IntegrationCustomUnpublished",
    "IntegrationCustomUpdated",
    "IntegrationDisconnected",
    "IntegrationError",
    "IntegrationInstructionsUpdated",
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
    budget_per_user_day: ClassVar[int] = 10

    integration_id: Identifier


class IntegrationInstructionsUpdated(ServerEvent):
    """A user edited an integration's custom instructions."""

    event: ClassVar[str] = "integration:instructions_updated"
    budget_per_user_day: ClassVar[int] = 10


class IntegrationCustomUpdated(ServerEvent):
    """A user edited a custom integration."""

    event: ClassVar[str] = "integration:custom_updated"
    budget_per_user_day: ClassVar[int] = 50


class IntegrationCustomDeleted(ServerEvent):
    """A user deleted a custom integration."""

    event: ClassVar[str] = "integration:custom_deleted"
    budget_per_user_day: ClassVar[int] = 50


class IntegrationCustomPublished(ServerEvent):
    """A user published a custom integration to the marketplace."""

    event: ClassVar[str] = "integration:custom_published"
    budget_per_user_day: ClassVar[int] = 50


class IntegrationCustomUnpublished(ServerEvent):
    """A user unpublished a custom integration."""

    event: ClassVar[str] = "integration:custom_unpublished"
    budget_per_user_day: ClassVar[int] = 50


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
    """A user installed a skill from GitHub or inline."""

    event: ClassVar[str] = "skill:installed"
    budget_per_user_day: ClassVar[int] = 10

    target: Identifier
    source: Literal["github", "inline"]
    skill_id: Identifier | None = None


class SkillUpdated(ServerEvent):
    """A user edited a skill."""

    event: ClassVar[str] = "skill:updated"
    budget_per_user_day: ClassVar[int] = 50


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
