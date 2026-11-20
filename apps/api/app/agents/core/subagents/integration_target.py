"""Resolve an integration id or short name to its platform subagent or custom MCP, without touching connections."""

from pydantic import BaseModel, ConfigDict

from app.agents.core.subagents.registry import get_subagent_by_id
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.mcp_config import MCPConfig
from app.models.subagent_models import Subagent
from app.services.integrations.integration_resolver import IntegrationResolver


class CustomMcpSubagent(BaseModel):
    """A user's custom MCP integration, as cached under ``SUBAGENT_CACHE_PREFIX``.

    Fields default because the cache holds whatever an earlier resolution wrote.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None
    source: str | None = None
    managed_by: str | None = None
    mcp_config: MCPConfig | None = None
    icon_url: str | None = None
    subagent_config: None = None


class _CustomIntegrationDoc(BaseModel):
    """The ``IntegrationResolver.custom_doc`` keys a custom-MCP target copies."""

    model_config = ConfigDict(extra="ignore")

    integration_id: str = ""
    name: str | None = None
    mcp_config: MCPConfig | None = None
    icon_url: str | None = None


async def get_integration_target(integration_id: str) -> Subagent | CustomMcpSubagent | None:
    """Resolve an integration id or short_name to a platform subagent or a custom MCP.

    Platform/built-in integrations come from the in-memory registry; custom MCPs
    come from MongoDB behind a Redis cache that also caches misses.
    """
    search_id = integration_id.lower().strip()

    subagent = get_subagent_by_id(search_id)
    if subagent:
        return subagent

    cache_key = f"{SUBAGENT_CACHE_PREFIX}:{search_id}"
    cached = await get_cache(cache_key)
    if cached is not None:
        # An empty dict is the cached miss.
        return CustomMcpSubagent.model_validate(cached) if cached else None

    custom = await integration_repository.find_by_id_prefix_or_name(search_id)
    if custom:
        result = CustomMcpSubagent(
            id=custom.integration_id,
            name=custom.name,
            source=custom.source,
            managed_by=custom.managed_by,
            mcp_config=custom.mcp_config,
            icon_url=custom.icon_url,
        )
        await set_cache(cache_key, result.model_dump(), ttl=SUBAGENT_CACHE_TTL)
        return result

    # Covers an integration present in user_integrations but not in integrations.
    resolved = await IntegrationResolver.resolve(search_id)
    if resolved and resolved.custom_doc:
        doc = _CustomIntegrationDoc.model_validate(resolved.custom_doc)
        result = CustomMcpSubagent(
            id=doc.integration_id,
            name=doc.name,
            source=resolved.source,
            managed_by="mcp",
            mcp_config=doc.mcp_config,
            icon_url=doc.icon_url,
        )
        await set_cache(cache_key, result.model_dump(), ttl=SUBAGENT_CACHE_TTL)
        return result

    await set_cache(cache_key, {}, ttl=SUBAGENT_CACHE_TTL)
    return None
