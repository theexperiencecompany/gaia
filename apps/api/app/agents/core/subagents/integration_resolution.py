"""Resolve an integration id to its target and gate it on the user's connection."""

from pydantic import BaseModel, ConfigDict

from app.agents.core.subagents.registry import get_subagent_by_id
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.subagent_models import Subagent
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import check_integration_status
from app.utils.integration_checker import request_integration_connection


class CustomMcpSubagent(BaseModel):
    """A user's custom MCP integration, as cached under ``SUBAGENT_CACHE_PREFIX``.

    Fields default because the cache holds whatever an earlier resolution wrote.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None
    source: str | None = None
    managed_by: str | None = None
    mcp_config: dict[str, object] | None = None
    icon_url: str | None = None
    subagent_config: None = None


class _CustomIntegrationDoc(BaseModel):
    """The ``IntegrationResolver.custom_doc`` keys a custom-MCP target copies.

    ``mcp_config`` stays the stored mapping: it is cached verbatim.
    """

    model_config = ConfigDict(extra="ignore")

    integration_id: str = ""
    name: str | None = None
    mcp_config: dict[str, object] | None = None
    icon_url: str | None = None


def _requires_auth(target: Subagent | CustomMcpSubagent) -> bool:
    if isinstance(target, CustomMcpSubagent):
        # The cached mcp_config is the stored mapping, not a validated MCPConfig.
        return target.mcp_config is not None and target.mcp_config.get("requires_auth") is True
    return target.managed_by == "mcp" and bool(
        target.mcp_config and target.mcp_config.requires_auth
    )


def is_per_user_mcp(target: Subagent | CustomMcpSubagent) -> bool:
    """Whether the target's tools are issued per user by an MCP server (never registry-bound)."""
    return isinstance(target, CustomMcpSubagent) or _requires_auth(target)


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
            mcp_config=custom.mcp_config.model_dump() if custom.mcp_config else None,
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


async def check_integration_connection(
    integration_id: str,
    user_id: str,
) -> str | None:
    """Return the connect prompt when a registry integration isn't connected, else None.

    Lives here rather than in integration_checker: it needs check_integration_status
    from oauth_service, which reaches integration_checker through composio.
    """
    subagent = get_subagent_by_id(integration_id)
    if not subagent:
        return None

    if await check_integration_status(integration_id, user_id):
        return None

    return await request_integration_connection(subagent.id, subagent.name, user_id)


async def check_mcp_connection(integration_id: str, user_id: str) -> str | None:
    """Return the connect prompt when an auth-requiring MCP has no usable credential, else None."""
    target = await get_integration_target(integration_id)
    if target is None or not _requires_auth(target):
        return None

    if await MCPTokenStore(user_id=user_id).is_connected(target.id):
        return None

    name = target.name if isinstance(target, Subagent) else (target.name or target.id)
    return await request_integration_connection(target.id, name, user_id)
