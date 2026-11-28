"""Resolve an integration id or short name to its platform subagent, connector or custom MCP, without touching connections."""

from pydantic import BaseModel, ConfigDict

from app.agents.core.subagents.registry import get_subagent_by_id
from app.config.oauth_config import get_integration_by_id
from app.db.repositories.integrations import integration_repository
from app.models.mcp_config import MCPConfig
from app.models.subagent_models import Subagent


class CustomMcpSubagent(BaseModel):
    """A user's custom MCP integration, projected from its integrations document."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None
    source: str | None = None
    managed_by: str | None = None
    mcp_config: MCPConfig | None = None
    icon_url: str | None = None
    subagent_config: None = None


async def get_integration_target(integration_id: str) -> Subagent | CustomMcpSubagent | None:
    """Resolve an integration id or short_name to a platform subagent or a custom MCP.

    Platform/built-in integrations come from the in-memory registry, catalog connectors
    from the code catalog; custom MCPs come from the integrations repository, which
    caches the lookup.
    """
    search_id = integration_id.lower().strip()

    subagent = get_subagent_by_id(search_id)
    if subagent:
        return subagent

    platform = get_integration_by_id(search_id)
    if platform is not None and platform.connector_config is not None:
        return CustomMcpSubagent(
            id=platform.id,
            name=platform.name,
            source="platform",
            managed_by=platform.managed_by,
            icon_url=platform.icon_url,
        )

    custom = await integration_repository.find_by_id_prefix_or_name(search_id)
    if custom is None:
        return None
    return CustomMcpSubagent(
        id=custom.integration_id,
        name=custom.name,
        source=custom.source,
        managed_by=custom.managed_by,
        mcp_config=custom.mcp_config,
        icon_url=custom.icon_url,
    )
