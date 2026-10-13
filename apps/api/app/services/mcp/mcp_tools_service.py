"""Global MCP tool metadata: Redis-cached roll-up over the integrations repository.

The repository owns the Mongo access (typed); this service adds the aggregate cache
(MCP_TOOLS_CACHE_KEY) and the dict-shaped views its callers consume. Writes bust
the roll-up cache so a freshly stored tool set is reflected on the next read.
"""

from collections.abc import Sequence
from typing import NotRequired, TypedDict

from app.constants.cache import MCP_TOOLS_CACHE_KEY, MCP_TOOLS_CACHE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.integration_models import McpToolsRollupEntry, StoredIntegrationTool
from shared.py.wide_events import log, spawn_logged_task

_ROLLUP = dict[str, McpToolsRollupEntry]


class RawToolMetadata(TypedDict):
    """One raw tool entry as producers build it, before _format_tools validates it."""

    name: str
    description: NotRequired[str | None]


def _format_tools(tools: Sequence[RawToolMetadata]) -> list[StoredIntegrationTool]:
    """Normalize raw tool dicts: strip whitespace, drop entries without a name."""
    formatted: list[StoredIntegrationTool] = []
    for tool in tools:
        name = tool["name"].strip()
        if name:
            formatted.append(
                StoredIntegrationTool(
                    name=name, description=(tool.get("description") or "").strip()
                )
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


async def invalidate_mcp_tools_cache() -> None:
    """Drop the global roll-up so the next read rebuilds it from the integrations repository."""
    await delete_cache(MCP_TOOLS_CACHE_KEY)


async def store_mcp_tools(integration_id: str, tools: Sequence[RawToolMetadata]) -> None:
    """Store tools for one MCP integration globally, then refresh the roll-up cache."""
    formatted = _format_tools(tools)
    if not formatted:
        return
    try:
        await integration_repository.store_tools(integration_id, formatted)
        await invalidate_mcp_tools_cache()
        _schedule_refresh()
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error storing tools",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def store_mcp_tools_batch(items: Sequence[tuple[str, Sequence[RawToolMetadata]]]) -> None:
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
        await invalidate_mcp_tools_cache()
        _schedule_refresh()
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error storing tools batch", error=str(e), error_type=type(e).__name__
        )
        raise


async def get_integration_tools(integration_id: str) -> list[StoredIntegrationTool]:
    """Return the stored tool metadata for an integration (empty on a read failure)."""
    try:
        return await integration_repository.get_tools(integration_id)
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error getting tools for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return []


async def get_all_mcp_tools() -> dict[str, McpToolsRollupEntry]:
    """All MCP tools with metadata, keyed by integration_id. Redis-cached 24h."""
    cached = await get_cache(MCP_TOOLS_CACHE_KEY, _ROLLUP)
    if cached:
        return cached

    try:
        grouped = {
            record.integration_id: McpToolsRollupEntry(
                tools=record.tools, name=record.name, icon_url=record.icon_url
            )
            for record in await integration_repository.all_with_tools()
            if record.integration_id and record.tools
        }
        await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL, model=_ROLLUP)
        return grouped
    except Exception as e:
        log.error(
            f"{LogTag.MCP} Error getting all MCP tools", error=str(e), error_type=type(e).__name__
        )
        return {}
