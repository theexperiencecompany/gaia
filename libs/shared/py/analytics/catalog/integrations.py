"""Integration, MCP and skill events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class IntegrationConnected(ServerEvent):
    """An integration or platform account finished connecting."""

    event: ClassVar[str] = "integration:connected"

    integration_id: Identifier
    auth_type: Literal["bearer", "none"] | None = None
    source: Literal["marketplace", "workspace"] | None = None
    managed_by: Identifier | None = None
    connection_method: Literal["oauth"] | None = None
    provider: Identifier | None = None
    is_new_link: bool | None = None
    # An OAuth callback for an integration this user had connected before (an expiry or re-auth).
    is_reconnect: bool | None = None


class IntegrationConnectInitiated(ServerEvent):
    """A connect flow was started and the user sent off to authorize it."""

    event: ClassVar[str] = "integration:connect_initiated"

    integration_id: Identifier
    auth_type: Identifier | None = None
    managed_by: Identifier | None = None
    source: Literal["connect_link"] | None = None


class IntegrationDisconnected(ServerEvent):
    """An integration or platform account was disconnected."""

    event: ClassVar[str] = "integration:disconnected"

    integration_id: Identifier


class IntegrationInstructionsUpdated(ServerEvent):
    """A user edited an integration's custom instructions."""

    event: ClassVar[str] = "integration:instructions_updated"

    integration_id: Identifier


class IntegrationCustomUpdated(ServerEvent):
    """A user edited a custom integration."""

    event: ClassVar[str] = "integration:custom_updated"

    integration_id: Identifier


class IntegrationCustomDeleted(ServerEvent):
    """A user deleted a custom integration."""

    event: ClassVar[str] = "integration:custom_deleted"

    integration_id: Identifier


class IntegrationCustomPublished(ServerEvent):
    """A user published a custom integration to the marketplace."""

    event: ClassVar[str] = "integration:custom_published"

    integration_id: Identifier


class IntegrationCustomUnpublished(ServerEvent):
    """A user unpublished a custom integration."""

    event: ClassVar[str] = "integration:custom_unpublished"

    integration_id: Identifier


class IntegrationError(WebEvent):
    """A connect or disconnect request failed in the browser."""

    event: ClassVar[str] = "integration:error"

    integration: Identifier
    # The failed request's HTTP status (0 for a transport failure) and the API's machine code; never its message.
    status: int | None = None
    error_code: Identifier | None = None


class McpConnectionTested(ServerEvent):
    """An MCP server connection probe finished."""

    event: ClassVar[str] = "mcp:connection_tested"

    status: Literal["connected", "failed", "requires_oauth"]
    tools_count: int | None = None


class SkillInstalled(ServerEvent):
    """A user installed a skill from GitHub or inline."""

    event: ClassVar[str] = "skill:installed"

    target: Identifier
    source: Literal["github", "inline"]
    skill_id: Identifier | None = None


class SkillUpdated(ServerEvent):
    """A user edited a skill."""

    event: ClassVar[str] = "skill:updated"


class SkillEnabled(ServerEvent):
    """A user enabled a skill."""

    event: ClassVar[str] = "skill:enabled"


class SkillDisabled(ServerEvent):
    """A user disabled a skill."""

    event: ClassVar[str] = "skill:disabled"


class SkillUninstalled(ServerEvent):
    """A user uninstalled a skill."""

    event: ClassVar[str] = "skill:uninstalled"

    skill_id: Identifier
    target: Identifier


class SkillSearched(WebEvent):
    """A user paused typing in the skills search box; the filter is client-side."""

    event: ClassVar[str] = "skill:searched"
