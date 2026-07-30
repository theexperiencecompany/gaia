"""Global MCP tool metadata: Redis-cached roll-up over the integrations repository.

The repository owns the Mongo access (typed); this service adds the aggregate cache
(``MCP_TOOLS_CACHE_KEY``) and the dict-shaped views its callers consume. Writes bust
the roll-up cache so a freshly stored tool set is reflected on the next read.
"""

from app.constants.cache import MCP_TOOLS_CACHE_KEY, MCP_TOOLS_CACHE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.integration_models import IntegrationTool
from shared.py.wide_events import log, spawn_logged_task


def _format_tools(tools: list[dict]) -> list[IntegrationTool]:
    """Normalize raw tool dicts: strip whitespace, drop entries without a name."""
    formatted: list[IntegrationTool] = []
    for tool in tools:
        name = tool.get("name", "").strip()
        if name:
            formatted.append(
                IntegrationTool(name=name, description=(tool.get("description") or "").strip())
            )
    return formatted


async def _refresh_cache() -> None:
    """Pre-warm the roll-up cache after a write (re-queries since the key was busted)."""
    try:
        await get_all_mcp_tools()
    except Exception as e:
        log.warning(
            f"{LogTag.MCP} Failed to refresh MCP tools cache",
            error=str(e),
            error_type=type(e).__name__,
        )


def _schedule_refresh() -> None:
    spawn_logged_task("mcp_tools_cache_refresh", _refresh_cache())


async def store_mcp_tools(integration_id: str, tools: list[dict]) -> None:
    """Store tools for one MCP integration globally, then refresh the roll-up cache."""
    formatted = _format_tools(tools)
    if not formatted:
        return
    try:
        await integration_repository.store_tools(integration_id, formatted)
        await delete_cache(MCP_TOOLS_CACHE_KEY)
        _schedule_refresh()
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error storing tools",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def store_mcp_tools_batch(items: list[tuple[str, list[dict]]]) -> None:
    """Store tools for several integrations in one pass, then refresh the roll-up cache."""
    formatted_items = [
        (integration_id, formatted)
        for integration_id, tools in items
        if (formatted := _format_tools(tools))
    ]
    if not formatted_items:
        return
    try:
        await integration_repository.store_tools_batch(formatted_items)
        await delete_cache(MCP_TOOLS_CACHE_KEY)
        _schedule_refresh()
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error storing tools batch", error=str(e), error_type=type(e).__name__
        )
        raise


async def get_integration_tools(integration_id: str) -> list[dict]:
    """Stored tools for an integration as plain dicts (frontend/display consumers)."""
    try:
        tools = await integration_repository.get_tools(integration_id)
        return [t.model_dump() for t in tools]
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error getting tools for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return []


async def get_all_mcp_tools() -> dict[str, dict]:
    """All MCP tools with metadata, keyed by integration_id. Redis-cached 24h."""
    cached = await get_cache(MCP_TOOLS_CACHE_KEY)
    if cached:
        return cached

    try:
        grouped: dict[str, dict] = {
            record.integration_id: {
                "tools": [t.model_dump() for t in record.tools],
                "name": record.name,
                "icon_url": record.icon_url,
            }
            for record in await integration_repository.all_with_tools()
            if record.integration_id and record.tools
        }
        await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL)
        return grouped
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error getting all MCP tools", error=str(e), error_type=type(e).__name__
        )
        return {}
